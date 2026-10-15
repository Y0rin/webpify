"""Batch-convert PNG images to WebP.

Usage:
    python convert.py SOURCE_DIR_OR_PNG OUTPUT_DIR [--width N] [--prefix TEXT] [--no-trim] [--force]

Default size mode is Auto: each PNG's canvas width decides its scale factor.
    canvas < 1000 px  -> object      -> scaled so the canvas would be 300 px  (600 -> 0.5)
    canvas >= 1000 px -> background  -> scaled so the canvas would be 960 px  (1200 -> 0.8)
The factor comes from the full canvas, then is applied to the trimmed image,
so every part keeps its drawn size relative to the others. Never upscales.
"""

import argparse
import re
import sys
from pathlib import Path

from PIL import Image

QUALITY = 82
BACKGROUND_MIN = 1000   # canvas width at or above this is a background
OBJECT_TARGET = 300
BACKGROUND_TARGET = 960


def clean_name(stem: str, prefix: str) -> str:
    """'Left Ear-2' -> 'left_ear_2' (with prefix prepended)."""
    name = stem.lower()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{prefix}{name}.webp"


def auto_factor(canvas_width: int) -> tuple[str, float]:
    """Return (type, scale factor) for a canvas width. Capped at 1.0."""
    if canvas_width >= BACKGROUND_MIN:
        kind, target = "background", BACKGROUND_TARGET
    else:
        kind, target = "object", OBJECT_TARGET
    return kind, min(1.0, target / canvas_width)


def scaled(size: tuple[int, int], factor: float) -> tuple[int, int]:
    return max(1, round(size[0] * factor)), max(1, round(size[1] * factor))


def convert(src: Path, dst: Path, width: int | None, trim: bool) -> dict:
    """Convert one PNG. width=None means Auto mode; otherwise exact output width."""
    with Image.open(src) as im:
        original = im.size
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (
            im.mode == "P" and "transparency" in im.info
        )
        im = im.convert("RGBA" if has_alpha else "RGB")

        if width:
            kind = "exact width"
        else:
            kind, factor = auto_factor(original[0])

        if trim and has_alpha:
            box = im.getchannel("A").getbbox()
            if box:
                im = im.crop(box)
        trimmed = im.size

        if width:
            factor = width / trimmed[0]
        final = scaled(trimmed, factor)
        if final != trimmed:
            im = im.resize(final, Image.LANCZOS)
        im.save(dst, "WEBP", quality=QUALITY, method=6)

    return {"original": original, "type": kind, "factor": factor,
            "trimmed": trimmed, "size": final}


def list_pngs(source: Path) -> list[Path]:
    return sorted(f for f in source.iterdir() if f.is_file() and f.suffix.lower() == ".png")


def convert_folder(source: Path, output: Path, width: int | None, prefix: str,
                   force: bool, trim: bool = True):
    """Convert every PNG in the source folder. See convert_files."""
    yield from convert_files(list_pngs(source), output, width, prefix, force, trim)


def convert_files(files: list[Path], output: Path, width: int | None, prefix: str,
                  force: bool, trim: bool = True):
    """Convert the given PNGs. Yields one result dict per file.

    status is "ok", "skip" or "fail"; ok results also carry the convert() info
    plus kb_before and kb_after.
    """
    output.mkdir(parents=True, exist_ok=True)
    for src in files:
        out_name = clean_name(src.stem, prefix)
        dst = output / out_name
        result = {"src": src.name, "out": out_name}
        if dst.exists() and not force:
            yield {**result, "status": "skip"}
            continue
        try:
            info = convert(src, dst, width, trim)
        except Exception as e:
            yield {**result, "status": "fail", "error": str(e)}
            continue
        yield {
            **result,
            **info,
            "status": "ok",
            "kb_before": src.stat().st_size / 1024,
            "kb_after": dst.stat().st_size / 1024,
        }


def fmt(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


def main() -> int:
    p = argparse.ArgumentParser(description="Batch-convert PNG images to WebP.")
    p.add_argument("source", type=Path, help="folder containing .png files, or a single .png")
    p.add_argument("output", type=Path, help="folder to write .webp files to")
    p.add_argument("--width", type=int, help="exact output width instead of Auto (e.g. 560 for covers)")
    p.add_argument("--prefix", default="", help="text added to every output name (e.g. p004_)")
    p.add_argument("--no-trim", action="store_true", help="keep transparent edges")
    p.add_argument("--force", action="store_true", help="overwrite existing output files")
    args = p.parse_args()

    if args.source.is_file() and args.source.suffix.lower() == ".png":
        files = [args.source]
    elif args.source.is_dir():
        files = list_pngs(args.source)
    else:
        print(f"Not a folder or .png file: {args.source}", file=sys.stderr)
        return 1
    if args.width is not None and args.width <= 0:
        print("--width must be a positive number", file=sys.stderr)
        return 1
    if not files:
        print(f"No .png files in {args.source}")
        return 0

    counts = {"ok": 0, "skip": 0, "fail": 0}
    total_before = total_after = 0
    for r in convert_files(files, args.output, args.width, args.prefix,
                           args.force, trim=not args.no_trim):
        counts[r["status"]] += 1
        if r["status"] == "skip":
            print(f"SKIP  {r['src']} -> {r['out']} (exists, use --force)")
        elif r["status"] == "fail":
            print(f"FAIL  {r['src']}: {r['error']}", file=sys.stderr)
        else:
            total_before += r["kb_before"]
            total_after += r["kb_after"]
            print(f"OK    {r['src']} -> {r['out']}  {fmt(r['original'])} {r['type']} "
                  f"x{r['factor']:.2f}  trimmed {fmt(r['trimmed'])} -> {fmt(r['size'])}  "
                  f"{r['kb_before']:.1f} KB -> {r['kb_after']:.1f} KB")

    print()
    print(f"Converted {counts['ok']}, skipped {counts['skip']}, failed {counts['fail']}.")
    if counts["ok"]:
        print(f"Total: {total_before:.1f} KB -> {total_after:.1f} KB")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
