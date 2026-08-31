"""Unit tests for Kavacha — Security & Privacy."""

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
import sarathi.kavacha as kavacha_module
from sarathi.sankalpa import SecurityDeclaration


class TestSecurityPolicy:
    def test_explicit_policy_construction_and_immutability(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=False,
            allowed_secrets=["OCR_API_KEY", "TRANSLATION_SECRET"],
        )
        assert policy.allow_pii_access is False
        assert policy.allow_network_access is True
        assert policy.allow_external_processing is False
        assert policy.allowed_secrets == ("OCR_API_KEY", "TRANSLATION_SECRET")

        # Immutability
        with pytest.raises(AttributeError):
            policy.allow_pii_access = True  # type: ignore

    def test_policy_rejects_non_bool_types(self) -> None:
        with pytest.raises(TypeError, match="allow_pii_access must be a bool"):
            SecurityPolicy(
                allow_pii_access=1,  # type: ignore
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets=(),
            )

        with pytest.raises(TypeError, match="allow_network_access must be a bool"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access="true",  # type: ignore
                allow_external_processing=False,
                allowed_secrets=(),
            )

        with pytest.raises(TypeError, match="allow_external_processing must be a bool"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=None,  # type: ignore
                allowed_secrets=(),
            )

    def test_policy_rejects_sets_and_invalid_secrets(self) -> None:
        # Reject sets
        with pytest.raises(TypeError, match="ordered sequence"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets={"SECRET_KEY"},  # type: ignore
            )

        # Reject non-string secret elements
        with pytest.raises(TypeError, match="must be strings"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets=(123,),  # type: ignore
            )

        # Reject empty secret names
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets=("",),
            )

        # Reject duplicate secrets
        with pytest.raises(ValueError, match="Duplicate secret"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets=("KEY_A", "KEY_A"),
            )


class TestKavachaAuthorization:
    def test_local_default_declaration_allowed(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            pii_access=False,
            local_processing_only=True,
            network_access=False,
            external_processing=False,
            required_secrets=(),
        )
        # Should succeed without error
        kavacha.authorize(decl)

    def test_pii_access_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(pii_access=True)

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED
        assert "PII access is not permitted" in err.message

    def test_network_access_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(network_access=True)

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED
        assert "Network access is not permitted" in err.message

    def test_external_processing_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
        )

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED
        assert "External processing is not permitted" in err.message

    def test_external_processing_denied_if_network_disallowed_in_policy(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,  # Network disallowed
            allow_external_processing=True,  # External allowed
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
        )

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED

    def test_disallowed_secret_denial_without_leaking_secret_name(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("APPROVED_KEY",),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("FORBIDDEN_PROPRIETARY_SECRET_XYZ",),
        )

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED
        # Verify secret names and sensitive content are not leaked in message or context
        assert "FORBIDDEN_PROPRIETARY_SECRET_XYZ" not in str(err)
        assert "FORBIDDEN_PROPRIETARY_SECRET_XYZ" not in str(dict(err.context))

    def test_allowed_secret_succeeds(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("APPROVED_KEY", "ANOTHER_KEY"),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("APPROVED_KEY",),
        )
        kavacha.authorize(decl)

    def test_invalid_arguments_to_kavacha(self) -> None:
        with pytest.raises(TypeError, match="policy must be a SecurityPolicy instance"):
            Kavacha("invalid_policy")  # type: ignore

        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        with pytest.raises(TypeError, match="declaration must be a SecurityDeclaration instance"):
            kavacha.authorize("not_a_declaration")  # type: ignore

    def test_kavacha_exports(self) -> None:
        expected = {"Kavacha", "SecurityPolicy"}
        assert set(kavacha_module.__all__) == expected
        for name in expected:
            assert hasattr(kavacha_module, name)
