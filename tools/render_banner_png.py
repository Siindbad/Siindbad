#!/usr/bin/env python3
"""Render SVG banner into a flat PNG for reliable GitHub profile display."""

from __future__ import annotations

import argparse
from pathlib import Path

import cairosvg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render profile banner PNG from SVG")
    parser.add_argument("--svg", required=True, help="Input SVG path")
    parser.add_argument("--png", required=True, help="Output PNG path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    svg_path = Path(args.svg)
    png_path = Path(args.png)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))
    print(f"Rendered {svg_path} -> {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
