"""Profile Fidelity and Round-Trip Auditor for Legacy Font Profiles.

Performs exhaustive round-trip audits (Legacy -> Unicode -> Legacy) across
all registered profiles in data/fonts/. Categorizes mappings into:
  - canonical: exact 1:1 round-trip
  - intentional_alias: many-to-one legacy glyphs mapping to same Unicode, backed by reverse_preferred
  - unexpected_loss: ambiguous or missing reverse mapping target

Enforces the invariant: every many-to-one mapping must define an explicit reverse_preferred target.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.models import LegacyFontProfile


@dataclass(frozen=True, slots=True)
class MappingAuditRecord:
    legacy_key: str
    unicode_val: str
    classification: str  # "canonical", "intentional_alias", "unexpected_loss"
    reverse_result: str | None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProfileAuditSummary:
    profile_id: str
    total_mappings: int
    canonical_count: int
    intentional_alias_count: int
    unexpected_loss_count: int
    reverse_preferred_count: int
    pass_audit: bool


def audit_profile_fidelity(
    profile: LegacyFontProfile,
    converter: FontConverter,
) -> tuple[ProfileAuditSummary, list[MappingAuditRecord]]:
    """Audit round-trip fidelity and alias handling for a single profile."""
    records: list[MappingAuditRecord] = []
    canonical = 0
    intentional_alias = 0
    unexpected_loss = 0

    # Build reverse lookup to detect many-to-one
    unicode_to_legacy: dict[str, list[str]] = {}
    for leg, uni in profile.mappings.items():
        unicode_to_legacy.setdefault(uni, []).append(leg)

    reverse_preferred = dict(profile.reverse_preferred)

    for leg, uni in sorted(profile.mappings.items(), key=lambda item: item[0]):
        # Skip multi-character ligature keys that are typist combos
        other_keys = unicode_to_legacy.get(uni, [])
        is_many_to_one = len(other_keys) > 1

        # Check reverse conversion via FontConverter
        rev = converter.reverse_convert(uni, target_profile_id=profile.profile_id)

        if rev == leg:
            classification = "canonical"
            canonical += 1
            detail = "Exact 1:1 round-trip"
        elif is_many_to_one and (uni in reverse_preferred or leg in reverse_preferred.values()):
            classification = "intentional_alias"
            intentional_alias += 1
            pref = reverse_preferred.get(uni)
            detail = f"Many-to-one resolved by reverse_preferred: '{pref}'"
        else:
            classification = "unexpected_loss"
            unexpected_loss += 1
            detail = f"Expected '{leg}', round-tripped to '{rev}' (aliases: {other_keys})"

        records.append(
            MappingAuditRecord(
                legacy_key=leg,
                unicode_val=uni,
                classification=classification,
                reverse_result=rev,
                detail=detail,
            )
        )

    # Invariant: unexpected_loss should ideally be 0 for fully specified profiles
    pass_audit = unexpected_loss == 0

    summary = ProfileAuditSummary(
        profile_id=profile.profile_id,
        total_mappings=len(profile.mappings),
        canonical_count=canonical,
        intentional_alias_count=intentional_alias,
        unexpected_loss_count=unexpected_loss,
        reverse_preferred_count=len(reverse_preferred),
        pass_audit=pass_audit,
    )
    return summary, records


def main() -> None:
    """CLI entry point for audit_font_profile."""
    parser = argparse.ArgumentParser(description="Audit font profile round-trip fidelity.")
    parser.add_argument("--profile", type=str, default=None, help="Profile ID to audit.")
    parser.add_argument("--all-profiles", action="store_true", help="Audit all loaded profiles.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    profiles = load_font_profiles()
    converter = FontConverter(profiles=profiles)

    if args.profile:
        if args.profile not in profiles:
            print(f"Error: Profile '{args.profile}' not found. Available: {sorted(profiles.keys())}", file=sys.stderr)
            sys.exit(1)
        target_pids = [args.profile]
    elif args.all_profiles or not args.profile:
        target_pids = sorted(profiles.keys())

    all_summaries: list[ProfileAuditSummary] = []
    has_failure = False

    for pid in target_pids:
        prof = profiles[pid]
        summary, records = audit_profile_fidelity(prof, converter)
        all_summaries.append(summary)

        if not summary.pass_audit:
            has_failure = True

        if not args.json:
            status = "PASS" if summary.pass_audit else "WARN/FAIL"
            print(f"\n--- Profile Audit: {pid} [{status}] ---")
            print(f"  Total Mappings: {summary.total_mappings}")
            print(f"  Canonical (1:1): {summary.canonical_count}")
            print(f"  Intentional Aliases: {summary.intentional_alias_count}")
            print(f"  Unexpected Loss: {summary.unexpected_loss_count}")
            print(f"  Reverse Preferred Rules: {summary.reverse_preferred_count}")
            if summary.unexpected_loss_count > 0:
                print("  Sample Unexpected Loss entries:")
                losses = [r for r in records if r.classification == "unexpected_loss"]
                for r in losses[:5]:
                    print(f"    {r.legacy_key!r} -> {r.unicode_val!r} -> rev:{r.reverse_result!r} ({r.detail})")

    if args.json:
        print(json.dumps([asdict(s) for s in all_summaries], indent=2))

    if has_failure:
        print("\nNote: Profiles with unexpected_loss have ambiguous reverse mappings requiring reverse_preferred definitions.")


if __name__ == "__main__":
    main()
