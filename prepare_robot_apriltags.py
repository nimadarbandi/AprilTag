#!/usr/bin/env python3
"""
prepare_robot_apriltags.py

Standalone utility for preparing AprilTags for a robot carrying a 1ft x 1ft cube.
This script does NOT modify existing calibration/tracking outputs. It only writes
to the target output directory (default: ./robot).

Outputs:
  robot/
    manifest.csv
    individual_tags/
      tag_0200.png
      tag_0200.pdf
      ...
    cube_faces/
      front_tag_0200_12in_sheet.png
      front_tag_0200_12in_sheet.pdf
      ...
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw

# Reuse the project's existing AprilTag generator backend/logic.
from generate_camera_mesh_and_apriltag_boards import generate_apriltag_image


FACE_NAMES: Tuple[str, ...] = ("front", "right", "back", "left", "top")
FACE_INSTALL_NOTES: Dict[str, str] = {
    "front": "Install on cube face pointing in robot forward direction.",
    "right": "Install on robot-right face when looking forward.",
    "back": "Install on opposite face of FRONT.",
    "left": "Install on robot-left face when looking forward.",
    "top": "Install on top face; keep text/arrow upright to robot front.",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prepare printable AprilTags for a 1ft x 1ft robot cube."
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("robot"),
        help="Output directory (default: robot).",
    )
    p.add_argument(
        "--april-family",
        type=str,
        default="tag36h11",
        help="AprilTag family (default: tag36h11).",
    )
    p.add_argument(
        "--start-tag-id",
        type=int,
        default=200,
        help="First tag id; 5 consecutive ids are used by default.",
    )
    p.add_argument(
        "--cube-face-size-in",
        type=float,
        default=12.0,
        help="Physical cube face size in inches (default: 12).",
    )
    p.add_argument(
        "--paper-size-in",
        type=float,
        default=12.0,
        help="Printable sheet size in inches (square page, e.g. 8 for 8x8).",
    )
    p.add_argument(
        "--tag-size-in",
        type=float,
        default=10.0,
        help="Printed tag size on each 12in face sheet (default: 10).",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Output DPI for PNG and PDF rasterization (default: 300).",
    )
    p.add_argument(
        "--strict-apriltag",
        action="store_true",
        help="Fail if true AprilTag generation backend is unavailable.",
    )
    return p.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.start_tag_id < 0:
        raise ValueError("start-tag-id must be >= 0.")
    if args.cube_face_size_in <= 0:
        raise ValueError("cube-face-size-in must be > 0.")
    if args.paper_size_in <= 0:
        raise ValueError("paper-size-in must be > 0.")
    if args.tag_size_in <= 0:
        raise ValueError("tag-size-in must be > 0.")
    if args.tag_size_in > args.cube_face_size_in:
        raise ValueError("tag-size-in must be <= cube-face-size-in.")
    if args.tag_size_in > args.paper_size_in:
        raise ValueError("tag-size-in must be <= paper-size-in.")
    if args.dpi <= 0:
        raise ValueError("dpi must be > 0.")


def _in_to_px(inches: float, dpi: int) -> int:
    return int(round(inches * dpi))


def _save_pdf(image: Image.Image, path: Path, dpi: int) -> None:
    image.convert("RGB").save(path, format="PDF", resolution=dpi)


def _render_face_sheet(
    tag_img: Image.Image,
    face: str,
    tag_id: int,
    family: str,
    face_size_in: float,
    paper_size_in: float,
    tag_size_in: float,
    face_px: int,
    tag_px: int,
) -> Image.Image:
    sheet = Image.new("RGB", (face_px, face_px), "white")
    tag_rgb = tag_img.convert("RGB")
    x0 = (face_px - tag_px) // 2
    y0 = (face_px - tag_px) // 2
    sheet.paste(tag_rgb, (x0, y0))

    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 0, face_px - 1, face_px - 1), outline="black", width=max(2, face_px // 400))
    draw.text((20, 12), f"FACE: {face.upper()}  |  TAG ID: {tag_id}", fill="black")
    draw.text((20, 34), f"FAMILY: {family}", fill="black")
    draw.text(
        (20, 56),
        f"CUBE FACE: {face_size_in:.1f} in  |  PAPER: {paper_size_in:.1f} in  |  TAG: {tag_size_in:.1f} in",
        fill="black",
    )
    draw.text((20, face_px - 64), f"MOUNT: {FACE_INSTALL_NOTES[face]}", fill="black")

    # Orientation cue so install direction is unambiguous.
    arrow_x = face_px - 120
    draw.line((arrow_x, 72, arrow_x, 22), fill="black", width=3)
    draw.polygon([(arrow_x, 14), (arrow_x - 8, 28), (arrow_x + 8, 28)], fill="black")
    draw.text((arrow_x - 20, 76), "UP", fill="black")

    # Print-scale check in the page margins.
    px_per_in = face_px / paper_size_in
    scale_in = 2.0
    if scale_in * px_per_in > face_px * 0.35:
        scale_in = 1.0
    scale_px = int(round(scale_in * px_per_in))

    # Horizontal scale bar near bottom-left.
    hx0, hy0 = 20, face_px - 26
    hx1 = hx0 + scale_px
    draw.line((hx0, hy0, hx1, hy0), fill="black", width=3)
    draw.line((hx0, hy0 - 8, hx0, hy0 + 8), fill="black", width=2)
    draw.line((hx1, hy0 - 8, hx1, hy0 + 8), fill="black", width=2)
    draw.text((hx0, hy0 - 22), f"PRINT CHECK: {scale_in:.0f} in", fill="black")

    # Vertical scale bar near bottom-right.
    vx0, vy0 = face_px - 26, face_px - 20
    vy1 = vy0 - scale_px
    draw.line((vx0, vy0, vx0, vy1), fill="black", width=3)
    draw.line((vx0 - 8, vy0, vx0 + 8, vy0), fill="black", width=2)
    draw.line((vx0 - 8, vy1, vx0 + 8, vy1), fill="black", width=2)
    draw.text((vx0 - 58, vy1 - 18), f"{scale_in:.0f} in", fill="black")
    return sheet


def _write_placement_guide(
    output_path: Path,
    family: str,
    cube_face_size_in: float,
    paper_size_in: float,
    tag_size_in: float,
    records: List[Tuple[str, int, str, str, str, str]],
) -> None:
    lines: List[str] = []
    lines.append("Robot AprilTag Placement Guide")
    lines.append("")
    lines.append(f"Family: {family}")
    lines.append(f"Cube size: {cube_face_size_in:.1f} in x {cube_face_size_in:.1f} in x {cube_face_size_in:.1f} in")
    lines.append(f"Paper size: {paper_size_in:.1f} in x {paper_size_in:.1f} in")
    lines.append(f"Tag print size: {tag_size_in:.1f} in")
    lines.append("")
    lines.append("Face mapping:")
    for face, tag_id, _, _, _, _ in records:
        lines.append(f"- {face.upper()}: tag ID {tag_id} | {FACE_INSTALL_NOTES[face]}")
    lines.append("")
    lines.append("Orientation:")
    lines.append("- Keep the 'UP' arrow on each sheet pointing upward on the installed cube face.")
    lines.append("- Keep all tags centered on each cube face.")
    lines.append("")
    lines.append("Standalone use:")
    lines.append("- Files under individual_tags/ can be used as independent single tags if needed.")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    _validate_args(args)

    output_dir: Path = args.output_dir
    faces_dir = output_dir / "cube_faces"
    individual_dir = output_dir / "individual_tags"
    output_dir.mkdir(parents=True, exist_ok=True)
    faces_dir.mkdir(parents=True, exist_ok=True)
    individual_dir.mkdir(parents=True, exist_ok=True)

    face_px = _in_to_px(args.paper_size_in, args.dpi)
    tag_px = _in_to_px(args.tag_size_in, args.dpi)

    records: List[Tuple[str, int, str, str, str, str]] = []

    for idx, face in enumerate(FACE_NAMES):
        tag_id = args.start_tag_id + idx
        tag_img = generate_apriltag_image(
            family=args.april_family,
            tag_id=tag_id,
            size_px=tag_px,
            strict_apriltag=args.strict_apriltag,
        )

        # Standalone tag file (independent use as a single tag).
        single_png = individual_dir / f"tag_{tag_id:04d}.png"
        single_pdf = individual_dir / f"tag_{tag_id:04d}.pdf"
        tag_img.save(single_png, format="PNG")
        _save_pdf(tag_img, single_pdf, args.dpi)

        # 12in face sheet for mounting on a cube face.
        sheet = _render_face_sheet(
            tag_img,
            face,
            tag_id,
            family=args.april_family,
            face_size_in=args.cube_face_size_in,
            paper_size_in=args.paper_size_in,
            tag_size_in=args.tag_size_in,
            face_px=face_px,
            tag_px=tag_px,
        )
        face_png = faces_dir / f"{face}_tag_{tag_id:04d}_{args.paper_size_in:.0f}in_sheet.png"
        face_pdf = faces_dir / f"{face}_tag_{tag_id:04d}_{args.paper_size_in:.0f}in_sheet.pdf"
        sheet.save(face_png, format="PNG", dpi=(args.dpi, args.dpi))
        _save_pdf(sheet, face_pdf, args.dpi)

        records.append((
            face,
            tag_id,
            str(face_png.relative_to(output_dir)),
            str(face_pdf.relative_to(output_dir)),
            str(single_png.relative_to(output_dir)),
            str(single_pdf.relative_to(output_dir)),
        ))

    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "face",
            "tag_id",
            "face_sheet_png",
            "face_sheet_pdf",
            "individual_tag_png",
            "individual_tag_pdf",
        ])
        writer.writerows(records)

    guide_path = output_dir / "placement_guide.txt"
    _write_placement_guide(
        output_path=guide_path,
        family=args.april_family,
        cube_face_size_in=args.cube_face_size_in,
        paper_size_in=args.paper_size_in,
        tag_size_in=args.tag_size_in,
        records=records,
    )

    print(f"Saved robot tag package to: {output_dir}")
    print(f"- Face sheets: {faces_dir}")
    print(f"- Individual tags: {individual_dir}")
    print(f"- Manifest: {manifest_path}")
    print(f"- Placement guide: {guide_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
