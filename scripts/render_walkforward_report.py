#!/usr/bin/env python3
"""Render WALKFORWARD_REPORT.md from an existing period_matrix.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.research_card import read_json, render_report_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("/opt/cursor/artifacts/walkforward_research_card/period_matrix.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Markdown output path (default: sibling WALKFORWARD_REPORT.md)",
    )
    args = parser.parse_args()
    card = read_json(args.matrix)
    out = args.out or (args.matrix.parent / "WALKFORWARD_REPORT.md")
    out.write_text(render_report_markdown(card))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
