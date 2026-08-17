from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import Config
from .persistence.sheets import SheetRepository
from .pipeline import run_harvest
from .runtime.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="captionflow-harvester", description="Captionflow Lead Harvester")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("harvest", help="Run one incremental lead harvest")
    sub.add_parser("bootstrap-sheet", help="Create/format the harvester Google Sheet tabs safely")
    sub.add_parser("validate-config", help="Validate environment configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        config = Config.from_env()
        if args.command == "validate-config":
            print(json.dumps({"valid": True, "has_public_sources": config.has_public_sources, "sheet_configured": bool(config.google_spreadsheet_id)}))
            return 0
        if args.command == "bootstrap-sheet":
            if not config.google_spreadsheet_id:
                raise ValueError("GOOGLE_SPREADSHEET_ID is required for bootstrap-sheet")
            SheetRepository(config.google_spreadsheet_id).bootstrap()
            print("Captionflow Lead Sheet initialized safely.")
            return 0
        if args.command == "harvest":
            if not config.has_public_sources:
                raise ValueError("Configure YOUTUBE_API_KEY and/or PUBLIC_* sources before harvesting")
            report = asyncio.run(run_harvest(config))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report.get("errors", 0) == 0 else 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
