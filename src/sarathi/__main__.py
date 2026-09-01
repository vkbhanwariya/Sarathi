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

    try:
        prof = ExecutionProfile.from_string(args.profile)
    except Exception:
        prof = ExecutionProfile.INSTANT

    first_path = Path(args.inputs[0])
    req_id = args.request_id or f"req-{first_path.stem or 'unnamed'}"
    input_refs: list[InputRef] = []
    for i, inp_str in enumerate(args.inputs):
        inp_path = Path(inp_str)
        try:
            size = inp_path.stat().st_size if inp_path.exists() else 0
        except OSError:
            size = 0
        input_refs.append(
            InputRef(
                input_id=f"inp-{i+1}",
                source_path=inp_path,
                display_name=inp_path.name,
                size_bytes=size,
            )
        )

    req = Request(
        request_id=req_id,
        requirement=args.requirement,
        inputs=tuple(input_refs),
        profile=prof,
        output_root=Path(args.output_root) if args.output_root else None,
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
