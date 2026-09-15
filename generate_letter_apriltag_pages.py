#!/usr/bin/env python3
"""Generate measured AprilTags on landscape Letter or Tabloid PDF pages.

One tag per page, with a clean white margin and a separate ID/UP label strip.
Example: python generate_letter_apriltag_pages.py --start-id 1 --end-id 20
         --paper-size tabloid --tag-size-in 10 --output tabloid_tags_1-20.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from generate_camera_mesh_and_apriltag_boards import generate_apriltag_image


LETTER_WIDTH_IN = 11.0
LETTER_HEIGHT_IN = 8.5
PAPER_SIZES = {"letter": (11.0, 8.5), "tabloid": (17.0, 11.0)}
DEFAULT_DPI = 300
DEFAULT_TAG_SIZE_IN = 8.0
WHITE_BORDER_IN = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a multipage Letter or Tabloid PDF containing one measured AprilTag "
            "per page for every ID in an inclusive range."
        )
    )
    parser.add_argument("--start-id", type=int, required=True, help="First tag ID, inclusive.")
    parser.add_argument("--end-id", type=int, required=True, help="Last tag ID, inclusive.")
    parser.add_argument("--family", default="tag36h11", help="AprilTag family (default: tag36h11).")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output PDF path. A descriptive filename is used when omitted.",
    )
    parser.add_argument("--paper-size", choices=tuple(PAPER_SIZES), default="letter",
                        help="Paper size, landscape (default: letter).")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Rendering DPI (default: 300).")
    parser.add_argument(
        "--tag-size-in", type=float, default=DEFAULT_TAG_SIZE_IN,
        help="Printed AprilTag outer width/height in inches (default: 8.0).",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_id < 0 or args.end_id < 0:
        raise ValueError("Tag IDs must be non-negative.")
    if args.end_id < args.start_id:
        raise ValueError("--end-id must be greater than or equal to --start-id.")
    if args.dpi < 72:
        raise ValueError("--dpi must be at least 72.")
    if args.tag_size_in <= 0:
        raise ValueError("Tag size must be positive.")
    target_span = args.tag_size_in + 2 * WHITE_BORDER_IN
    if target_span > min(PAPER_SIZES[args.paper_size]) + 1e-9:
        raise ValueError("The tag plus its two 0.25-inch borders must fit on the landscape page.")


def inches_to_px(inches: float, dpi: int) -> int:
    return int(round(inches * dpi))


def load_font(point_size: float, dpi: int, bold: bool = False) -> ImageFont.ImageFont:
    pixel_size = max(8, int(round(point_size * dpi / 72.0)))
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, pixel_size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_identity_and_orientation(
    page: Image.Image, tag_id: int, family: str, tag_size_in: float, dpi: int, paper_size: str = "letter"
) -> None:
    """Use only the right annotation strip; preserve the tag's quiet border."""
    draw = ImageDraw.Draw(page)
    color = 55
    width_in, height_in = PAPER_SIZES[paper_size]
    center_x = inches_to_px((height_in + width_in) / 2, dpi)

    small_bold = load_font(14, dpi, bold=True)
    id_font = load_font(48, dpi, bold=True)
    detail_font = load_font(10, dpi)

    draw.text((center_x, inches_to_px(0.60, dpi)), "TOP / UP", fill=color,
              font=small_bold, anchor="ma")

    # Compact upward cue, kept well away from the AprilTag itself.
    shaft_width = max(2, inches_to_px(0.020, dpi))
    tip_y = inches_to_px(1.10, dpi)
    head_base_y = inches_to_px(1.28, dpi)
    shaft_bottom_y = inches_to_px(1.75, dpi)
    half_head = inches_to_px(0.12, dpi)
    draw.line((center_x, shaft_bottom_y, center_x, head_base_y),
              fill=color, width=shaft_width)
    draw.polygon(
        ((center_x, tip_y), (center_x - half_head, head_base_y),
         (center_x + half_head, head_base_y)),
        fill=color,
    )

    draw.text((center_x, inches_to_px(3.55, dpi)), "APRILTAG", fill=color,
              font=small_bold, anchor="ma")
    draw.text((center_x, inches_to_px(4.15, dpi)), f"ID {tag_id}", fill=color,
              font=id_font, anchor="ma")
    draw.text((center_x, inches_to_px(5.25, dpi)), family, fill=color,
              font=detail_font, anchor="ma")
    draw.text((center_x, inches_to_px(5.62, dpi)), f"{tag_size_in:.3f} in tag", fill=color,
              font=detail_font, anchor="ma")


def render_page(tag_id: int, family: str, tag_size_in: float, dpi: int, paper_size: str = "letter") -> Image.Image:
    width_in, height_in = PAPER_SIZES[paper_size]
    page_width = inches_to_px(width_in, dpi)
    page_height = inches_to_px(height_in, dpi)
    tag_px = inches_to_px(tag_size_in, dpi)
    x0 = inches_to_px(WHITE_BORDER_IN, dpi)
    y_top = inches_to_px(WHITE_BORDER_IN, dpi)

    marker = generate_apriltag_image(
        family=family, tag_id=tag_id, size_px=tag_px, strict_apriltag=True
    ).convert("L")
    page = Image.new("L", (page_width, page_height), 255)
    page.paste(marker, (x0, y_top))
    draw_identity_and_orientation(page, tag_id, family, tag_size_in, dpi, paper_size)
    return page


def save_multipage_pdf(pages: Iterable[Image.Image], destination: Path, dpi: int, paper_size: str = "letter") -> int:
    rendered = list(pages)
    if not rendered:
        raise ValueError("No pages were generated.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered[0].save(
        destination, format="PDF", save_all=True, append_images=rendered[1:],
        resolution=dpi, title=f"Measured AprilTag US {paper_size.title()} pages",
        author="AprilTag print generator",
    )
    return len(rendered)


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        output = args.output or Path(
            f"apriltag_{args.family}_{args.start_id:04d}_to_{args.end_id:04d}_{args.paper_size}.pdf"
        )
        pages = (
            render_page(tag_id, args.family, args.tag_size_in, args.dpi, args.paper_size)
            for tag_id in range(args.start_id, args.end_id + 1)
        )
        count = save_multipage_pdf(pages, output, args.dpi, args.paper_size)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {count} US {args.paper_size.title()} pages to: {output.resolve()}")
    print(f"Tag IDs: {args.start_id} through {args.end_id} (inclusive)")
    print(f"Family: {args.family}; printed tag size: {args.tag_size_in:.3f} in")
    print("Print landscape using Actual Size / 100%; disable Fit to Page and scaling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
