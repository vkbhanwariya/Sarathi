"""Sarathi V2 CLI and Non-Interactive Runtime Entry Point.

Hands execution strictly to Agni composition root.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sarathi.agni import Agni
from sarathi.dosh import DoshError
from sarathi.sankalpa import ExecutionProfile, InputRef, Request


def main(argv: list[str] | None = None) -> int:
    """Run Sarathi non-interactive execution."""
    parser = argparse.ArgumentParser(
        prog="sarathi",
        description="Sarathi V2 - Local, Plugin-First Document Intelligence System",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to Sutra settings TOML configuration file",
    )
    parser.add_argument(
        "--input",
        "-i",
        action="append",
        dest="inputs",
        help="Path to input document file (can be specified multiple times)",
    )
    parser.add_argument(
        "--requirement",
        "-r",
        type=str,
        default="read_native",
        help="Target processing requirement (e.g. 'read_native', 'ocr')",
    )
    parser.add_argument(
        "--recursive",
        "-R",
        action="store_true",
        default=False,
        help="Recursively scan selected directories for input document files",
    )
    parser.add_argument(
        "--profile",
        "-p",
        type=str,
        default="instant",
        help="Execution profile (instant, accurate, layout_preserving, custom)",
    )
    parser.add_argument(
        "--output-root",
        "-o",
        type=str,
        default=None,
        help="Output storage root directory",
    )
    parser.add_argument(
        "--runtime-root",
        type=str,
        default=None,
        help="Runtime staging storage root directory",
    )
    parser.add_argument(
        "--request-id",
        type=str,
        default=None,
        help="Explicit request identifier",
    )

    args = parser.parse_args(argv)

    if not args.inputs:
        parser.print_help(sys.stderr)
        return 2

    # 1. Strict profile parsing
    try:
        prof = ExecutionProfile.from_string(args.profile)
    except ValueError:
        print(
            f"Validation error: Invalid profile '{args.profile}'. "
            f"Allowed profiles: {[p.value for p in ExecutionProfile]}",
            file=sys.stderr,
        )
        return 2

    # 2. Canonical intake via MukhaPresenter
    from sarathi.mukha.presenter import MukhaPresenter

    runtime_root = Path(args.runtime_root) if args.runtime_root else None
    output_root = Path(args.output_root) if args.output_root else None

    input_refs, selection, preflight = MukhaPresenter.intake_from_paths(
        args.inputs,
        runtime_root=runtime_root,
        output_root=output_root,
        recursive=args.recursive,
    )

    if preflight.issues:
        for name, reason in preflight.issues:
            if "does not exist" in reason.lower():
                print(f"Validation error: Input path does not exist: {name}", file=sys.stderr)
            elif "not a regular file" in reason.lower():
                print(f"Validation error: Input path is not a regular file: {name}", file=sys.stderr)
            elif "duplicate" in reason.lower():
                print(f"Validation error: Duplicate input file selected: {name}", file=sys.stderr)
            else:
                print(f"Validation error: {name} - {reason}", file=sys.stderr)
        return 2

    if not input_refs:
        print("Validation error: No eligible input files found.", file=sys.stderr)
        return 2

    first_display = input_refs[0].display_name
    req_id = args.request_id or f"req-{Path(first_display).stem or 'unnamed'}"

    req = Request(
        request_id=req_id,
        requirement=args.requirement,
        inputs=input_refs,
        profile=prof,
        output_root=output_root,
    )

    try:
        with Agni(
            settings=Path(args.config) if args.config else None,
            runtime_root=Path(args.runtime_root) if args.runtime_root else None,
            output_root=Path(args.output_root) if args.output_root else None,
        ) as agni:
            result = agni.execute(req)
            print(f"Status: Success (Requirement: {req.requirement})")
            if result.confidence is not None:
                print(f"Confidence: {result.confidence.score:.2f}")
            return 0
    except DoshError as dosh_err:
        print(f"Error: {dosh_err.code.name} - {dosh_err.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: Internal execution error - {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
