#!/usr/bin/env python3
"""CLI: Seedream generate + grid crop → PNG files in an output directory."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from seedream_assets import generate_and_crop_assets, load_spec_file, write_assets_to_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate game assets via Seedream and crop sprite sheets.")
    parser.add_argument("--prompt", help="Image generation prompt (overrides spec file prompt)")
    parser.add_argument(
        "--spec",
        type=Path,
        help="JSON spec file with { prompt?, sheets: [{ rows, cols, assetNames }] }",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write cropped PNG files (e.g. artifact assets folder)",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print saved relative paths as JSON to stdout",
    )
    args = parser.parse_args()

    if args.spec:
        spec = load_spec_file(args.spec)
    else:
        spec = json.load(sys.stdin)

    prompt = (args.prompt or spec.get("prompt") or "").strip()
    sheets = spec.get("sheets") or []
    if not prompt:
        parser.error("prompt is required (--prompt or spec.prompt)")
    if not sheets:
        parser.error("sheets must be a non-empty array")

    assets = generate_and_crop_assets(prompt=prompt, sheets=sheets)
    saved = write_assets_to_dir(assets, args.output_dir)

    if args.print_json:
        rel = [Path(p).name for p in saved]
        print(json.dumps({"saved": rel, "count": len(rel)}, ensure_ascii=False))
    else:
        for path in saved:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
