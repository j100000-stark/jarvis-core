"""Command-line entry point for JARVIS."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .config import Settings
from .core import Assistant


def build_parser() -> argparse.ArgumentParser:
    """Build the small V0.1 command-line interface."""
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS — a modular autonomous AI assistant foundation.",
    )
    parser.add_argument(
        "--memory-file",
        help="Path to the JSON memory file (defaults to the configured data directory).",
    )
    parser.add_argument(
        "--once",
        metavar="MESSAGE",
        help="Process one message and exit instead of opening an interactive session.",
    )
    parser.add_argument(
        "--goal",
        metavar="GOAL",
        help="Plan and execute one high-level goal using the configured Brain.",
    )
    parser.add_argument(
        "--system-report",
        action="store_true",
        help="Output a JSON system report (health, network, recovery, security) and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Start JARVIS from the command line."""
    args = build_parser().parse_args(argv)
    settings = Settings.from_environment(memory_file=args.memory_file)
    assistant = Assistant(settings)

    if args.system_report:
        report = assistant.system_report()
        print(json.dumps(report))
        return

    if args.goal is not None:
        print(assistant.respond(f"goal {args.goal}"))
        return

    if args.once is not None:
        print(assistant.respond(args.once))
        return

    print(assistant.startup_message())
    while True:
        try:
            message = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJARVIS> Session closed.")
            break

        if not message:
            continue
        if message.lower() in {"exit", "quit", "goodbye"}:
            print("JARVIS> Session closed.")
            break
        print(f"JARVIS> {assistant.respond(message)}")


if __name__ == "__main__":
    main()
