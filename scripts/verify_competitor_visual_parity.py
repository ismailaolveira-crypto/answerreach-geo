"""Generate reproducible YON-18 visual comparison artifacts from fixed screenshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageOps


VIEWPORTS = ((1496, 846), (1440, 1000), (390, 844))

# Tight rectangles around business-dependent summary copy and values only.
# Card edges, dividers, colors, controls, typography placement, and shadows remain compared.
DYNAMIC_TEXT_MASKS = {
    "1496x846": [
        (88, 306, 526, 336),
        (88, 345, 430, 359),
        (567, 307, 700, 338),
        (567, 345, 700, 360),
        (770, 307, 876, 338),
        (770, 345, 900, 360),
        (970, 307, 1050, 338),
        (970, 345, 1118, 360),
        (1176, 307, 1410, 329),
    ],
    "1440x1000": [
        (80, 306, 518, 336),
        (80, 345, 422, 359),
        (547, 307, 680, 338),
        (547, 345, 680, 360),
        (748, 307, 854, 338),
        (748, 345, 878, 360),
        (946, 307, 1026, 338),
        (946, 345, 1094, 360),
        (1144, 307, 1382, 329),
    ],
}


def compare_pair(root: Path, width: int, height: int, threshold: int) -> dict[str, object]:
    label = f"{width}x{height}"
    reference_path = root / f"reference-{label}.png"
    implementation_path = root / f"implementation-{label}.png"
    reference = Image.open(reference_path).convert("RGB")
    implementation = Image.open(implementation_path).convert("RGB")
    if reference.size != (width, height) or implementation.size != (width, height):
        raise ValueError(
            f"{label}: expected {(width, height)}, got reference={reference.size}, "
            f"implementation={implementation.size}"
        )

    side_by_side = Image.new("RGB", (width * 2, height), "white")
    side_by_side.paste(reference, (0, 0))
    side_by_side.paste(implementation, (width, 0))
    side_by_side.save(root / f"side-by-side-{label}.png")

    Image.blend(reference, implementation, 0.5).save(root / f"overlay-50-{label}.png")

    difference = ImageChops.difference(reference, implementation)
    different = difference.convert("L").point(lambda value: 255 if value > threshold else 0)
    changed_pixels = different.histogram()[255]
    total_pixels = width * height

    dynamic_mask = Image.new("L", reference.size, 0)
    mask_draw = ImageDraw.Draw(dynamic_mask)
    mask_rectangles = DYNAMIC_TEXT_MASKS.get(label, [])
    for rectangle in mask_rectangles:
        mask_draw.rectangle(rectangle, fill=255)
    masked_different = ImageChops.subtract(different, dynamic_mask)
    masked_changed_pixels = masked_different.histogram()[255]

    mask_preview = reference.copy()
    mask_overlay = Image.new("RGB", reference.size, (28, 158, 119))
    mask_preview.paste(Image.blend(reference, mask_overlay, 0.28), mask=dynamic_mask)
    mask_preview.save(root / f"dynamic-text-mask-{label}.png")

    grayscale = ImageOps.grayscale(reference).convert("RGB")
    grayscale = ImageEnhance.Brightness(grayscale).enhance(1.15)
    highlight = Image.new("RGB", reference.size, (225, 35, 115))
    grayscale.paste(highlight, mask=different)
    grayscale.save(root / f"diff-{label}.png")

    return {
        "viewport": label,
        "threshold": threshold,
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "raw_changed_ratio": round(changed_pixels / total_pixels, 6),
        "dynamic_text_mask_rectangles": mask_rectangles,
        "masked_changed_pixels": masked_changed_pixels,
        "masked_changed_ratio": round(masked_changed_pixels / total_pixels, 6),
        "reference": reference_path.name,
        "implementation": implementation_path.name,
        "side_by_side": f"side-by-side-{label}.png",
        "overlay_50": f"overlay-50-{label}.png",
        "diff": f"diff-{label}.png",
        "mask_preview": f"dynamic-text-mask-{label}.png",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("output/playwright/yon18"))
    parser.add_argument("--threshold", type=int, default=16)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    comparisons = [
        compare_pair(args.root, width, height, args.threshold)
        for width, height in VIEWPORTS
    ]
    report = {
        "schema_version": 1,
        "comparison": "reference vs r3 implementation at identical viewport and scroll=0",
        "threshold": args.threshold,
        "dynamic_text_masked": True,
        "note": "Both raw and masked ratios are reported. Masks cover only tight business-dependent summary text/value rectangles; card geometry, dividers, colors, controls, typography placement, and shadows remain compared.",
        "viewports": comparisons,
    }
    report_path = args.root / "visual-diff-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
