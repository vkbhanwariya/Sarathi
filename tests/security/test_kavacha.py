from pathlib import Path

import pytest

import sarathi.kavacha as kavacha_module
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityDecision, SecurityPolicy
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

    def test_policy_consistency_rejects_external_without_network(self) -> None:
        with pytest.raises(ValueError, match="allow_external_processing=True requires allow_network_access=True"):
            SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=True,
                allowed_secrets=(),
            )

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


class TestSecurityPolicyEvaluation:
    def test_evaluate_local_allowed(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        decl = SecurityDeclaration(
            pii_access=False,
            local_processing_only=True,
            network_access=False,
            external_processing=False,
            required_secrets=(),
        )
        decision = policy.evaluate(decl)
        assert isinstance(decision, SecurityDecision)
        assert decision.allowed is True
        assert decision.message is None

    def test_evaluate_fully_permissive_allowed(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("TRANSLATION_API_KEY", "OCR_KEY"),
        )
        decl = SecurityDeclaration(
            pii_access=True,
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("TRANSLATION_API_KEY",),
        )
        decision = policy.evaluate(decl)
        assert decision.allowed is True
        assert decision.message is None

    def test_evaluate_pii_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=(),
        )
        decl = SecurityDeclaration(pii_access=True, network_access=False)
        decision = policy.evaluate(decl)
        assert decision.allowed is False
        assert decision.message is not None
        assert "PII access is not permitted" in decision.message

    def test_evaluate_network_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        decl = SecurityDeclaration(network_access=True)
        decision = policy.evaluate(decl)
        assert decision.allowed is False
        assert decision.message is not None
        assert "Network access is not permitted" in decision.message

    def test_evaluate_external_processing_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
        )
        decision = policy.evaluate(decl)
        assert decision.allowed is False
        assert decision.message is not None
        assert "External processing is not permitted" in decision.message

    def test_evaluate_disallowed_secret_denial(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("KEY_A",),
        )
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("UNAPPROVED_KEY",),
        )
        decision = policy.evaluate(decl)
        assert decision.allowed is False
        assert decision.message is not None
        assert "One or more required secrets are not permitted" in decision.message


class TestKavachaService:
    def test_kavacha_delegates_to_policy_and_allows(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("APPROVED_SECRET",),
        )
        kavacha = Kavacha(policy)
        assert kavacha.policy is policy

        decl = SecurityDeclaration(
            pii_access=True,
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("APPROVED_SECRET",),
        )
        # Should succeed without exception
        kavacha.authorize(decl)

    def test_kavacha_denial_raises_dosh_error_without_leaking_secrets(self) -> None:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        decl = SecurityDeclaration(
            network_access=True,
            external_processing=True,
            local_processing_only=False,
            required_secrets=("SECRET_TOKEN_XYZ",),
        )

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize(decl)

        err = exc_info.value
        assert err.code is FailureCode.SECURITY_DENIED
        assert "SECRET_TOKEN_XYZ" not in str(err)
        assert "SECRET_TOKEN_XYZ" not in str(dict(err.context))

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
        expected = {"Kavacha", "OutboundRequest", "SecurityDecision", "SecurityPolicy"}
        assert set(kavacha_module.__all__) == expected
        for name in expected:
            assert hasattr(kavacha_module, name)


class TestKavachaSourceDestinationOverlap:
    @pytest.fixture
    def kavacha(self) -> Kavacha:
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        return Kavacha(policy)

    def test_disjoint_source_and_destination_allowed(self, kavacha: Kavacha, tmp_path: Path) -> None:
        src_file = tmp_path / "inputs" / "doc.pdf"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_bytes(b"DATA")

        dest_dir = tmp_path / "output" / "Run-1"
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Should execute cleanly without error
        kavacha.validate_source_destination_overlap([src_file], [dest_dir])

    def test_source_inside_destination_rejected(self, kavacha: Kavacha, tmp_path: Path) -> None:
        dest_dir = tmp_path / "output" / "Run-1"
        dest_dir.mkdir(parents=True, exist_ok=True)

        bad_src = dest_dir / "sneaky_input.pdf"
        bad_src.write_bytes(b"DATA")

        with pytest.raises(DoshError) as exc_info:
            kavacha.validate_source_destination_overlap([bad_src], dest_dir)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Unsafe source and destination overlap" in exc_info.value.message
        assert str(bad_src) not in exc_info.value.message
        assert str(dest_dir) not in exc_info.value.message

    def test_destination_inside_source_rejected(self, kavacha: Kavacha, tmp_path: Path) -> None:
        src_dir = tmp_path / "inputs"
        src_dir.mkdir(parents=True, exist_ok=True)

        bad_dest = src_dir / "nested_output"
        bad_dest.mkdir(parents=True, exist_ok=True)

        with pytest.raises(DoshError) as exc_info:
            kavacha.validate_source_destination_overlap([src_dir], [bad_dest])

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "Unsafe source and destination overlap" in exc_info.value.message
        assert str(src_dir) not in exc_info.value.message
        assert str(bad_dest) not in exc_info.value.message

    def test_invalid_types_raise_type_error(self, kavacha: Kavacha, tmp_path: Path) -> None:
        with pytest.raises(TypeError, match="source_paths must be a sequence"):
            kavacha.validate_source_destination_overlap("not_a_seq", tmp_path)  # type: ignore

        with pytest.raises(TypeError, match="destination_roots must be a Path, str, or sequence"):
            kavacha.validate_source_destination_overlap([tmp_path], 123)  # type: ignore


class TestKavachaOutboundGate:
    def test_outbound_request_validation(self) -> None:
        from sarathi.kavacha import OutboundRequest

        with pytest.raises(ValueError, match="destination must be a non-empty string"):
            OutboundRequest(destination="")

        with pytest.raises(TypeError, match="payload_classification must be a str"):
            OutboundRequest(destination="https://example.com", payload_classification=123)  # type: ignore

        with pytest.raises(TypeError, match="requires_external_processing must be a bool"):
            OutboundRequest(destination="https://example.com", requires_external_processing="yes")  # type: ignore

        req = OutboundRequest(
            destination="https://example.com/api",
            payload_classification="pii",
            requires_external_processing=True,
            required_secrets=("KEY1",),
        )
        assert req.destination == "https://example.com/api"
        assert req.payload_classification == "pii"
        assert req.requires_external_processing is True
        assert req.required_secrets == ("KEY1",)

    def test_outbound_network_access_rejected_when_forbidden(self) -> None:
        from sarathi.kavacha import OutboundRequest

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        req = OutboundRequest(destination="https://example.com/api")

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize_outbound(req)
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "network access is not permitted" in exc_info.value.message.lower()

    def test_outbound_external_processing_rejected_when_forbidden(self) -> None:
        from sarathi.kavacha import OutboundRequest

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        req = OutboundRequest(destination="https://example.com/api", requires_external_processing=True)

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize_outbound(req)
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "external processing is not permitted" in exc_info.value.message.lower()

    def test_outbound_pii_rejected_when_forbidden(self) -> None:
        from sarathi.kavacha import OutboundRequest

        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        req = OutboundRequest(destination="https://example.com/api", payload_classification="document_content")

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize_outbound(req)
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "sensitive payload is not permitted" in exc_info.value.message.lower()

    def test_outbound_unauthorized_secret_rejected(self) -> None:
        from sarathi.kavacha import OutboundRequest

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("AUTHORIZED_KEY",),
        )
        kavacha = Kavacha(policy)
        req = OutboundRequest(destination="https://example.com/api", required_secrets=("FORBIDDEN_KEY",))

        with pytest.raises(DoshError) as exc_info:
            kavacha.authorize_outbound(req)
        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert "is not permitted by" in exc_info.value.message.lower()

    def test_outbound_permitted_when_all_conditions_satisfied(self) -> None:
        from sarathi.kavacha import OutboundRequest

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=("TRANSLATE_KEY",),
        )
        kavacha = Kavacha(policy)
        req = OutboundRequest(
            destination="https://api.translation.service/v1",
            payload_classification="document_content",
            requires_external_processing=True,
            required_secrets=("TRANSLATE_KEY",),
        )
        # Succeeded without error
        kavacha.authorize_outbound(req)
