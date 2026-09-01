"""Kavacha — Security & Privacy Service for Sarathi V2.

Delegates authorization decisions to SecurityPolicy.
Contains no filesystem I/O, secret storage, PII scanning, network clients,
logging, or telemetry.
"""

from pathlib import Path
from typing import Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha.policy import SecurityDecision, SecurityPolicy
from sarathi.sankalpa import InputRef, SecurityDeclaration


class Kavacha:
    """Security authorization service for Sarathi runtime."""

    def __init__(self, policy: SecurityPolicy) -> None:
        if not isinstance(policy, SecurityPolicy):
            raise TypeError(f"policy must be a SecurityPolicy instance, got {type(policy).__name__}.")
        self._policy: SecurityPolicy = policy

    @property
    def policy(self) -> SecurityPolicy:
        """Return the active immutable SecurityPolicy."""
        return self._policy

    def authorize(self, declaration: SecurityDeclaration) -> None:
        """Authorize a plugin/capability security declaration against the active policy.

        Raises:
            DoshError(FailureCode.SECURITY_DENIED): If any declared requirement violates policy.
            TypeError: If declaration is not a SecurityDeclaration.
        """
        if not isinstance(declaration, SecurityDeclaration):
            raise TypeError(
                f"declaration must be a SecurityDeclaration instance, got {type(declaration).__name__}."
            )

        decision = self._policy.evaluate(declaration)
        if not decision.allowed:
            raise DoshError(
                code=FailureCode.SECURITY_DENIED,
                message=decision.message or "Security policy denied authorization.",
            )

    def validate_source_destination_overlap(
        self,
        source_paths: Sequence[Path | str | InputRef],
        destination_roots: Sequence[Path | str] | Path | str,
    ) -> None:
        """Validate that input source paths and destination storage roots do not overlap.

        Rejects:
        - Any source file located within a destination root (staging, work, or output directory).
        - Any destination root located within or equal to an input source file or folder.

        Raises:
            DoshError(FailureCode.SECURITY_DENIED): On unsafe source/destination overlap or escape.
            TypeError: On invalid input types.
        """
        if not isinstance(source_paths, (list, tuple)):
            raise TypeError(f"source_paths must be a sequence, got {type(source_paths).__name__}.")

        dest_list: list[Path] = []
        if isinstance(destination_roots, (Path, str)):
            dest_list = [Path(destination_roots).resolve()]
        elif isinstance(destination_roots, (list, tuple)):
            dest_list = [Path(d).resolve() for d in destination_roots]
        else:
            raise TypeError(f"destination_roots must be a Path, str, or sequence, got {type(destination_roots).__name__}.")

        for i, src in enumerate(source_paths):
            if isinstance(src, InputRef):
                raw_path = src.source_path
            elif isinstance(src, (Path, str)):
                raw_path = Path(src)
            else:
                raise TypeError(f"source_paths[{i}] must be a Path, str, or InputRef, got {type(src).__name__}.")

            try:
                resolved_src = raw_path.resolve()
            except OSError as err:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Failed to inspect source path.",
                ) from err

            for dest_root in dest_list:
                # 1. Source cannot be inside or equal to destination root
                try:
                    resolved_src.relative_to(dest_root)
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Unsafe source and destination overlap: input source resides within destination directory.",
                    )
                except ValueError:
                    pass

                # 2. Destination root cannot be inside or equal to source path
                try:
                    dest_root.relative_to(resolved_src)
                    raise DoshError(
                        code=FailureCode.SECURITY_DENIED,
                        message="Unsafe source and destination overlap: destination directory resides within input source.",
                    )
                except ValueError:
                    pass
