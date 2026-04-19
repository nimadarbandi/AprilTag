#!/usr/bin/env python3
"""
Generate camera coverage meshes and printable AprilTag calibration boards.

Usage example
-------------
python generate_camera_mesh_and_apriltag_boards.py \
  --field_width_ft 96 \
  --field_height_ft 27 \
  --cam_width_ft 14 \
  --cam_height_ft 7 \
  --overlap_x_ratio 0.18 \
  --overlap_y_ratio 0.20 \
  --board_width_ft 2 \
  --board_height_ft 2 \
  --output_dir output_96x27

This script:
- Builds a camera mesh from field dimensions, camera coverage, and overlap.
- Places one 4-tag board at each internal camera-view intersection.
- Exports:
  - camera layout plan (PDF + PNG)
  - camera and board manifests (CSV)
  - per-board printable PDFs + PNGs
  - optional tiled poster-friendly board PDFs
  - visibility reports

Coordinate convention
---------------------
- Origin is bottom-left of the field.
- X increases along field_width_ft.
- Y increases along field_height_ft.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

FALLBACK_TAG_WARNING_PRINTED = False


PAGE_SIZES_IN: Dict[str, Tuple[float, float]] = {
    "letter": (8.5, 11.0),
    "a4": (8.27, 11.69),
    "tabloid": (11.0, 17.0),
}


@dataclass(frozen=True)
class Camera:
    camera_id: str
    row_index: int
    col_index: int
    x_center_ft: float
    y_center_ft: float
    x_min_ft: float
    x_max_ft: float
    y_min_ft: float
    y_max_ft: float


@dataclass(frozen=True)
class Board:
    board_id: str
    row_index: int
    col_index: int
    x_left_ft: float
    y_bottom_ft: float
    tag_ids: Tuple[int, int, int, int]


@dataclass(frozen=True)
class AxisMesh:
    centers: List[float]
    stride_target_ft: float
    stride_used_ft: float
    overlap_used_ft: float
    left_margin_ft: float
    right_margin_ft: float
    preferred_margin_ft: float
    hard_min_margin_ft: float
    effective_overlap_ratio: float


@dataclass(frozen=True)
class Config:
    field_width_ft: float
    field_height_ft: float
    cam_width_ft: float
    cam_height_ft: float
    overlap_x_ratio: float
    overlap_y_ratio: float
    min_edge_coverage_ratio: float
    min_edge_margin_ft: float
    target_overlap_x_ft: float
    target_overlap_y_ft: float
    coord_step_ft: float
    board_width_ft: float
    board_height_ft: float
    board_offset_x_ft: float
    board_offset_y_ft: float
    tags_per_board: int
    april_family: str
    start_tag_id: int
    output_dir: Path
    board_page_size: str
    board_page_width_in: float
    board_page_height_in: float
    board_png_dpi: int
    min_tag_size_in: float
    tag_size_in: float | None
    tag_gap_in: float
    board_inner_margin_in: float
    header_height_in: float
    footer_height_in: float
    tiled_output: bool
    tile_page_size: str
    tile_page_width_in: float
    tile_page_height_in: float
    tile_overlap_in: float
    tile_dpi: int
    plan_line_labels: bool
    plan_line_label_fontsize: int
    plan_line_decimals: int
    plan_camera_label_fontsize: int
    board_near_camera_fontsize: int
    strict_apriltag: bool


def parse_args(argv: Sequence[str]) -> Config:
    parser = argparse.ArgumentParser(
        description="Generate camera mesh + AprilTag board layout and printable files."
    )
    parser.add_argument("--field_width_ft", type=float, required=True)
    parser.add_argument("--field_height_ft", type=float, required=True)
    parser.add_argument("--cam_width_ft", type=float, required=True)
    parser.add_argument("--cam_height_ft", type=float, required=True)
    parser.add_argument("--overlap_x_ratio", type=float, required=True)
    parser.add_argument("--overlap_y_ratio", type=float, required=True)
    parser.add_argument(
        "--min_edge_coverage_ratio",
        type=float,
        default=0.10,
        help="Preferred fraction of camera FOV that extends beyond each field boundary.",
    )
    parser.add_argument(
        "--min_edge_margin_ft",
        type=float,
        default=1.0,
        help="Hard minimum outside margin (ft) per field boundary.",
    )
    parser.add_argument(
        "--target_overlap_x_ft",
        type=float,
        default=2.0,
        help="Preferred overlap width between adjacent cameras in X (ft).",
    )
    parser.add_argument(
        "--target_overlap_y_ft",
        type=float,
        default=2.0,
        help="Preferred overlap width between adjacent cameras in Y (ft).",
    )
    parser.add_argument(
        "--coord_step_ft",
        type=float,
        default=0.5,
        help="Snap camera and board coordinates to this grid step (ft).",
    )
    parser.add_argument("--board_width_ft", type=float, default=2.0)
    parser.add_argument("--board_height_ft", type=float, default=2.0)
    parser.add_argument("--board_offset_x_ft", type=float, default=0.0)
    parser.add_argument("--board_offset_y_ft", type=float, default=0.0)
    parser.add_argument("--tags_per_board", type=int, default=4)
    parser.add_argument("--april_family", type=str, default="tag36h11")
    parser.add_argument("--start_tag_id", type=int, default=0)
    parser.add_argument("--output_dir", type=Path, default=Path("output"))

    parser.add_argument(
        "--board_page_size",
        type=str,
        default="letter",
        choices=["letter", "a4", "tabloid", "custom"],
        help="Per-board PDF/PNG page size.",
    )
    parser.add_argument("--board_page_width_in", type=float, default=8.5)
    parser.add_argument("--board_page_height_in", type=float, default=11.0)
    parser.add_argument("--board_png_dpi", type=int, default=300)
    parser.add_argument(
        "--min_tag_size_in",
        type=float,
        default=8.0,
        help="Minimum printed size per tag in inches (width and height).",
    )
    parser.add_argument(
        "--tag_size_in",
        type=float,
        default=None,
        help=(
            "Exact printed tag size in inches. If omitted, script maximizes tag size "
            "subject to margins and headers."
        ),
    )
    parser.add_argument(
        "--tag_gap_in",
        type=float,
        default=0.25,
        help="Gap between adjacent tags in inches.",
    )
    parser.add_argument(
        "--board_inner_margin_in",
        type=float,
        default=0.25,
        help="Inner page margin around the 2x2 tag grid in inches.",
    )
    parser.add_argument(
        "--header_height_in",
        type=float,
        default=0.55,
        help="Reserved header strip height in inches (kept compact by default).",
    )
    parser.add_argument(
        "--footer_height_in",
        type=float,
        default=0.35,
        help="Reserved footer strip height in inches (kept compact by default).",
    )

    parser.add_argument(
        "--tiled_output",
        action="store_true",
        help="Also create tiled poster-friendly board PDFs from a full-size board image.",
    )
    parser.add_argument(
        "--tile_page_size",
        type=str,
        default="letter",
        choices=["letter", "a4", "tabloid", "custom"],
        help="Tile page size used for tiled board PDFs.",
    )
    parser.add_argument("--tile_page_width_in", type=float, default=8.5)
    parser.add_argument("--tile_page_height_in", type=float, default=11.0)
    parser.add_argument("--tile_overlap_in", type=float, default=0.25)
    parser.add_argument("--tile_dpi", type=int, default=300)
    parser.add_argument(
        "--plan_line_labels",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show coordinate labels for each camera boundary line on the global plan.",
    )
    parser.add_argument(
        "--plan_line_label_fontsize",
        type=int,
        default=6,
        help="Font size used for line-coordinate labels on the global plan.",
    )
    parser.add_argument(
        "--plan_line_decimals",
        type=int,
        default=1,
        help="Decimal places for line-coordinate labels on the global plan.",
    )
    parser.add_argument(
        "--plan_camera_label_fontsize",
        type=int,
        default=10,
        help="Font size for camera IDs on the global camera layout plan.",
    )
    parser.add_argument(
        "--board_near_camera_fontsize",
        type=int,
        default=16,
        help="Font size for 'near Cxx' labels on each board under tag IDs.",
    )
    parser.add_argument(
        "--strict_apriltag",
        action="store_true",
        help="Fail if a true AprilTag backend is unavailable.",
    )

    args = parser.parse_args(argv)

    validate_positive(args.field_width_ft, "field_width_ft")
    validate_positive(args.field_height_ft, "field_height_ft")
    validate_positive(args.cam_width_ft, "cam_width_ft")
    validate_positive(args.cam_height_ft, "cam_height_ft")
    validate_positive(args.board_width_ft, "board_width_ft")
    validate_positive(args.board_height_ft, "board_height_ft")
    validate_positive(args.board_png_dpi, "board_png_dpi")
    validate_positive(args.min_tag_size_in, "min_tag_size_in")
    if args.tag_size_in is not None and args.tag_size_in <= 0:
        raise ValueError("tag_size_in must be > 0 when provided.")
    if args.tag_gap_in < 0:
        raise ValueError("tag_gap_in must be >= 0.")
    if args.board_inner_margin_in < 0:
        raise ValueError("board_inner_margin_in must be >= 0.")
    if args.header_height_in < 0 or args.footer_height_in < 0:
        raise ValueError("header_height_in and footer_height_in must be >= 0.")
    validate_positive(args.tile_dpi, "tile_dpi")
    if args.plan_line_label_fontsize <= 0:
        raise ValueError("plan_line_label_fontsize must be > 0.")
    if args.plan_line_decimals < 0:
        raise ValueError("plan_line_decimals must be >= 0.")
    if args.plan_camera_label_fontsize <= 0:
        raise ValueError("plan_camera_label_fontsize must be > 0.")
    if args.board_near_camera_fontsize <= 0:
        raise ValueError("board_near_camera_fontsize must be > 0.")

    validate_ratio(args.overlap_x_ratio, "overlap_x_ratio")
    validate_ratio(args.overlap_y_ratio, "overlap_y_ratio")
    if not (0.0 <= args.min_edge_coverage_ratio < 0.5):
        raise ValueError("min_edge_coverage_ratio must be in [0.0, 0.5).")
    if args.min_edge_margin_ft < 0:
        raise ValueError("min_edge_margin_ft must be >= 0.")
    if args.target_overlap_x_ft < 0 or args.target_overlap_y_ft < 0:
        raise ValueError("target_overlap_x_ft and target_overlap_y_ft must be >= 0.")
    validate_positive(args.coord_step_ft, "coord_step_ft")

    if args.tags_per_board != 4:
        raise ValueError("This layout currently supports exactly 4 tags per board.")
    if args.start_tag_id < 0:
        raise ValueError("start_tag_id must be >= 0.")
    if args.tile_overlap_in < 0:
        raise ValueError("tile_overlap_in must be >= 0.")

    return Config(
        field_width_ft=args.field_width_ft,
        field_height_ft=args.field_height_ft,
        cam_width_ft=args.cam_width_ft,
        cam_height_ft=args.cam_height_ft,
        overlap_x_ratio=args.overlap_x_ratio,
        overlap_y_ratio=args.overlap_y_ratio,
        min_edge_coverage_ratio=args.min_edge_coverage_ratio,
        min_edge_margin_ft=args.min_edge_margin_ft,
        target_overlap_x_ft=args.target_overlap_x_ft,
        target_overlap_y_ft=args.target_overlap_y_ft,
        coord_step_ft=args.coord_step_ft,
        board_width_ft=args.board_width_ft,
        board_height_ft=args.board_height_ft,
        board_offset_x_ft=args.board_offset_x_ft,
        board_offset_y_ft=args.board_offset_y_ft,
        tags_per_board=args.tags_per_board,
        april_family=args.april_family.lower(),
        start_tag_id=args.start_tag_id,
        output_dir=args.output_dir,
        board_page_size=args.board_page_size,
        board_page_width_in=args.board_page_width_in,
        board_page_height_in=args.board_page_height_in,
        board_png_dpi=args.board_png_dpi,
        min_tag_size_in=args.min_tag_size_in,
        tag_size_in=args.tag_size_in,
        tag_gap_in=args.tag_gap_in,
        board_inner_margin_in=args.board_inner_margin_in,
        header_height_in=args.header_height_in,
        footer_height_in=args.footer_height_in,
        tiled_output=args.tiled_output,
        tile_page_size=args.tile_page_size,
        tile_page_width_in=args.tile_page_width_in,
        tile_page_height_in=args.tile_page_height_in,
        tile_overlap_in=args.tile_overlap_in,
        tile_dpi=args.tile_dpi,
        plan_line_labels=args.plan_line_labels,
        plan_line_label_fontsize=args.plan_line_label_fontsize,
        plan_line_decimals=args.plan_line_decimals,
        plan_camera_label_fontsize=args.plan_camera_label_fontsize,
        board_near_camera_fontsize=args.board_near_camera_fontsize,
        strict_apriltag=args.strict_apriltag,
    )


def validate_positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0.")


def validate_ratio(value: float, name: str) -> None:
    if not (0.0 < value < 1.0):
        raise ValueError(f"{name} must be between 0 and 1 (exclusive).")
    if value < 0.10 or value > 0.30:
        print(
            f"Warning: {name}={value:.3f} is outside the recommended 0.10-0.30 range.",
            file=sys.stderr,
        )


def page_size_inches(name: str, width_in: float, height_in: float) -> Tuple[float, float]:
    if name == "custom":
        validate_positive(width_in, "custom page width")
        validate_positive(height_in, "custom page height")
        return (width_in, height_in)
    return PAGE_SIZES_IN[name]


def snap_to_step(value: float, step_ft: float) -> float:
    return round(value / step_ft) * step_ft


def ceil_to_step(value: float, step_ft: float) -> float:
    return math.ceil(value / step_ft) * step_ft


def compute_axis_centers(
    field_span_ft: float,
    cam_span_ft: float,
    overlap_ratio: float,
    min_edge_coverage_ratio: float,
    min_edge_margin_ft: float,
    target_overlap_ft: float,
    coord_step_ft: float,
) -> AxisMesh:
    stride_target = cam_span_ft * (1.0 - overlap_ratio)
    if stride_target <= 0:
        raise ValueError("Computed stride is <= 0. Check overlap ratio.")

    preferred_margin_ft = cam_span_ft * min_edge_coverage_ratio
    hard_min_margin_ft = min_edge_margin_ft

    if field_span_ft <= cam_span_ft:
        center = snap_to_step(field_span_ft / 2.0, coord_step_ft)
        left_margin = cam_span_ft / 2.0 - center
        right_margin = center + cam_span_ft / 2.0 - field_span_ft
        overlap_used = 0.0
        return AxisMesh(
            centers=[center],
            stride_target_ft=stride_target,
            stride_used_ft=0.0,
            overlap_used_ft=overlap_used,
            left_margin_ft=left_margin,
            right_margin_ft=right_margin,
            preferred_margin_ft=preferred_margin_ft,
            hard_min_margin_ft=hard_min_margin_ft,
            effective_overlap_ratio=0.0,
        )

    base_count = int(math.ceil((field_span_ft - cam_span_ft) / stride_target)) + 1
    candidate_counts = range(max(2, base_count - 2), base_count + 6)

    best_mesh: AxisMesh | None = None
    best_score = float("inf")
    tol = 1e-9

    for count in candidate_counts:
        stride_floor = max(
            0.0,
            (field_span_ft + 2.0 * hard_min_margin_ft - cam_span_ft) / (count - 1),
        )
        stride_floor = ceil_to_step(stride_floor, coord_step_ft)
        stride_overlap_target = cam_span_ft - target_overlap_ft
        stride_overlap_target = max(0.0, snap_to_step(stride_overlap_target, coord_step_ft))
        stride_seed = max(stride_floor, stride_overlap_target, 0.0)

        if stride_seed <= 0:
            continue

        for k in range(0, 16):
            stride_used = stride_seed + k * coord_step_ft

            x0_ideal = (field_span_ft - (count - 1) * stride_used) / 2.0
            x0 = snap_to_step(x0_ideal, coord_step_ft)
            centers = [x0 + i * stride_used for i in range(count)]

            left_margin = cam_span_ft / 2.0 - centers[0]
            right_margin = centers[-1] + cam_span_ft / 2.0 - field_span_ft

            if left_margin < -tol or right_margin < -tol:
                continue
            if (
                left_margin + tol < hard_min_margin_ft
                or right_margin + tol < hard_min_margin_ft
            ):
                continue

            overlap_used = cam_span_ft - stride_used
            effective_overlap = 1.0 - (stride_used / cam_span_ft)
            symmetry_delta = abs(left_margin - right_margin)
            outside_excess = (
                max(0.0, left_margin - hard_min_margin_ft)
                + max(0.0, right_margin - hard_min_margin_ft)
            )
            overlap_error = abs(overlap_used - target_overlap_ft)
            preferred_shortfall = (
                max(0.0, preferred_margin_ft - left_margin)
                + max(0.0, preferred_margin_ft - right_margin)
            )
            score = (
                20.0 * outside_excess
                + 10.0 * symmetry_delta
                + 6.0 * overlap_error
                + 4.0 * abs(count - base_count)
                + 1.0 * abs(stride_used - stride_target)
                + 0.5 * preferred_shortfall
            )
            if score < best_score:
                best_score = score
                best_mesh = AxisMesh(
                    centers=centers,
                    stride_target_ft=stride_target,
                    stride_used_ft=stride_used,
                    overlap_used_ft=overlap_used,
                    left_margin_ft=left_margin,
                    right_margin_ft=right_margin,
                    preferred_margin_ft=preferred_margin_ft,
                    hard_min_margin_ft=hard_min_margin_ft,
                    effective_overlap_ratio=effective_overlap,
                )

    if best_mesh is None:
        raise ValueError(
            "Could not build a valid axis mesh with the requested overlap, boundary margin, "
            "and coordinate step. Try lowering --min_edge_coverage_ratio or --coord_step_ft."
        )
    return best_mesh


def build_cameras(cfg: Config) -> Tuple[List[Camera], AxisMesh, AxisMesh]:
    x_axis = compute_axis_centers(
        cfg.field_width_ft,
        cfg.cam_width_ft,
        cfg.overlap_x_ratio,
        cfg.min_edge_coverage_ratio,
        cfg.min_edge_margin_ft,
        cfg.target_overlap_x_ft,
        cfg.coord_step_ft,
    )
    y_axis = compute_axis_centers(
        cfg.field_height_ft,
        cfg.cam_height_ft,
        cfg.overlap_y_ratio,
        cfg.min_edge_coverage_ratio,
        cfg.min_edge_margin_ft,
        cfg.target_overlap_y_ft,
        cfg.coord_step_ft,
    )

    cameras: List[Camera] = []
    total_cameras = len(y_axis.centers) * len(x_axis.centers)
    id_width = max(2, len(str(total_cameras)))
    camera_seq = 1
    for r, y in enumerate(y_axis.centers):
        for c, x in enumerate(x_axis.centers):
            cam_id = f"C{camera_seq:0{id_width}d}"
            cameras.append(
                Camera(
                    camera_id=cam_id,
                    row_index=r,
                    col_index=c,
                    x_center_ft=x,
                    y_center_ft=y,
                    x_min_ft=x - cfg.cam_width_ft / 2.0,
                    x_max_ft=x + cfg.cam_width_ft / 2.0,
                    y_min_ft=y - cfg.cam_height_ft / 2.0,
                    y_max_ft=y + cfg.cam_height_ft / 2.0,
                )
            )
            camera_seq += 1
    return cameras, x_axis, y_axis


def build_boards(cfg: Config, x_centers: Sequence[float], y_centers: Sequence[float]) -> List[Board]:
    boards: List[Board] = []
    board_idx = 0
    x_left_max = max(0.0, cfg.field_width_ft - cfg.board_width_ft)
    y_bottom_max = max(0.0, cfg.field_height_ft - cfg.board_height_ft)
    for r in range(len(y_centers) - 1):
        y_raw = (y_centers[r] + y_centers[r + 1]) / 2.0 + cfg.board_offset_y_ft
        for c in range(len(x_centers) - 1):
            x_raw = (x_centers[c] + x_centers[c + 1]) / 2.0 + cfg.board_offset_x_ft
            x_left = snap_to_step(
                x_raw - cfg.board_width_ft / 2.0,
                cfg.coord_step_ft,
            )
            y_bottom = snap_to_step(
                y_raw - cfg.board_height_ft / 2.0,
                cfg.coord_step_ft,
            )
            x_left = float(np.clip(x_left, 0.0, x_left_max))
            y_bottom = float(np.clip(y_bottom, 0.0, y_bottom_max))

            tag_base = cfg.start_tag_id + board_idx * cfg.tags_per_board
            tag_ids = (tag_base, tag_base + 1, tag_base + 2, tag_base + 3)
            boards.append(
                Board(
                    board_id=f"B{board_idx + 1:02d}",
                    row_index=r,
                    col_index=c,
                    x_left_ft=x_left,
                    y_bottom_ft=y_bottom,
                    tag_ids=tag_ids,
                )
            )
            board_idx += 1
    return boards


def validate_tag_uniqueness(boards: Sequence[Board]) -> None:
    all_ids: List[int] = [tag_id for b in boards for tag_id in b.tag_ids]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Tag IDs are not unique across boards.")


def validate_board_coordinates(boards: Sequence[Board], cfg: Config) -> None:
    out_of_bounds = [
        b
        for b in boards
        if not (
            0.0 <= b.x_left_ft <= cfg.field_width_ft - cfg.board_width_ft
            and 0.0 <= b.y_bottom_ft <= cfg.field_height_ft - cfg.board_height_ft
        )
    ]
    if out_of_bounds:
        bad_ids = ", ".join(b.board_id for b in out_of_bounds[:5])
        raise ValueError(f"Board coordinates out of field bounds: {bad_ids}")


def _opencv_family_id(family: str) -> int:
    if cv2 is None or not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV aruco backend is unavailable.")
    fam = family.lower()
    family_map = {
        "tag16h5": cv2.aruco.DICT_APRILTAG_16h5,
        "tag25h9": cv2.aruco.DICT_APRILTAG_25h9,
        "tag36h10": cv2.aruco.DICT_APRILTAG_36h10,
        "tag36h11": cv2.aruco.DICT_APRILTAG_36h11,
    }
    if fam not in family_map:
        supported = ", ".join(sorted(family_map.keys()))
        raise ValueError(f"Unsupported AprilTag family '{family}'. Supported: {supported}")
    return family_map[fam]


def generate_apriltag_image(
    family: str, tag_id: int, size_px: int, strict_apriltag: bool
) -> Image.Image:
    global FALLBACK_TAG_WARNING_PRINTED

    if size_px <= 0:
        raise ValueError("size_px must be > 0.")
    if tag_id < 0:
        raise ValueError("tag_id must be >= 0.")

    if cv2 is not None and hasattr(cv2, "aruco"):
        dictionary_id = _opencv_family_id(family)
        dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        max_tags = int(dictionary.bytesList.shape[0])
        if tag_id >= max_tags:
            raise ValueError(
                f"tag_id {tag_id} is out of range for {family}. Max id is {max_tags - 1}."
            )

        marker: np.ndarray
        try:
            marker = cv2.aruco.generateImageMarker(dictionary, tag_id, size_px)
        except Exception:
            marker = np.zeros((size_px, size_px), dtype=np.uint8)
            if hasattr(cv2.aruco, "drawMarker"):
                cv2.aruco.drawMarker(dictionary, tag_id, size_px, marker, 1)
            else:
                raise RuntimeError("OpenCV aruco marker generation is unavailable.")
        return Image.fromarray(marker).convert("L")

    if strict_apriltag:
        raise RuntimeError(
            "No valid AprilTag generation backend found. Install opencv-contrib-python "
            "or run without --strict_apriltag to use placeholder tags."
        )

    # Fallback placeholder is deterministic but not a true AprilTag.
    if not FALLBACK_TAG_WARNING_PRINTED:
        print(
            "Warning: Using placeholder tag images because no AprilTag generator backend was found.",
            file=sys.stderr,
        )
        FALLBACK_TAG_WARNING_PRINTED = True

    img = Image.new("L", (size_px, size_px), color=255)
    draw = ImageDraw.Draw(img)
    border = max(2, size_px // 24)
    draw.rectangle((0, 0, size_px - 1, size_px - 1), outline=0, width=border)
    draw.rectangle(
        (size_px // 6, size_px // 6, 5 * size_px // 6, 5 * size_px // 6),
        outline=0,
        width=border,
    )
    text = f"{family}\nID {tag_id}\nplaceholder"
    draw.multiline_text((size_px * 0.12, size_px * 0.40), text, fill=0, spacing=4)
    return img


def fixed_board_canvas_size_in(cfg: Config) -> Tuple[float, float]:
    # Board canvas is locked to the physical board dimensions.
    return cfg.board_width_ft * 12.0, cfg.board_height_ft * 12.0


def draw_dimension_line(
    ax: plt.Axes,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    label: str,
    text_x: float,
    text_y: float,
    rotation: float = 0.0,
) -> None:
    ax.annotate(
        "",
        xy=(x0, y0),
        xytext=(x1, y1),
        arrowprops={"arrowstyle": "<->", "lw": 1.0, "color": "#555555"},
    )
    ax.text(
        text_x,
        text_y,
        label,
        fontsize=8,
        color="#444444",
        ha="center" if rotation == 0 else "right",
        va="center",
        rotation=rotation,
        bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "#bbbbbb", "alpha": 0.9},
    )


def draw_edge_rulers(
    ax: plt.Axes,
    page_w: float,
    page_h: float,
    safe_x_clearance: float,
    safe_y_clearance: float,
) -> None:
    # Keep rulers inside the clear border area so they don't overlap tags.
    ruler_h = min(0.22, max(0.08, safe_y_clearance * 0.7))
    ruler_w = min(0.22, max(0.08, safe_x_clearance * 0.7))

    # Bottom horizontal ruler in inches.
    max_x = int(math.floor(page_w))
    for xi in range(max_x + 1):
        is_major = (xi % 2 == 0)
        tick = ruler_h if is_major else ruler_h * 0.65
        ax.plot([xi, xi], [0.0, tick], color="#4a4a4a", lw=0.9)
        if is_major:
            ax.text(
                xi,
                tick + 0.02,
                f'{xi}"',
                ha="center",
                va="bottom",
                fontsize=6,
                color="#444444",
            )

    # Left vertical ruler in inches.
    max_y = int(math.floor(page_h))
    for yi in range(max_y + 1):
        is_major = (yi % 2 == 0)
        tick = ruler_w if is_major else ruler_w * 0.65
        ax.plot([0.0, tick], [yi, yi], color="#4a4a4a", lw=0.9)
        if is_major:
            ax.text(
                tick + 0.02,
                yi,
                f'{yi}"',
                ha="left",
                va="center",
                fontsize=6,
                color="#444444",
            )


def draw_scale_bar(
    ax: plt.Axes, x0: float, y0: float, length_in: float, label: str, vertical: bool = False
) -> None:
    if not vertical:
        ax.plot([x0, x0 + length_in], [y0, y0], color="#222222", lw=3.2, solid_capstyle="butt")
        ax.plot([x0, x0], [y0 - 0.08, y0 + 0.08], color="#222222", lw=1.4)
        ax.plot([x0 + length_in, x0 + length_in], [y0 - 0.08, y0 + 0.08], color="#222222", lw=1.4)
        ax.text(
            x0 + length_in / 2.0,
            y0 + 0.12,
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color="#222222",
            fontweight="bold",
        )
    else:
        ax.plot([x0, x0], [y0, y0 + length_in], color="#222222", lw=3.2, solid_capstyle="butt")
        ax.plot([x0 - 0.08, x0 + 0.08], [y0, y0], color="#222222", lw=1.4)
        ax.plot([x0 - 0.08, x0 + 0.08], [y0 + length_in, y0 + length_in], color="#222222", lw=1.4)
        ax.text(
            x0 + 0.12,
            y0 + length_in / 2.0,
            label,
            ha="left",
            va="center",
            fontsize=8,
            color="#222222",
            rotation=90,
            fontweight="bold",
    )


def build_camera_grid_lookup(cameras: Sequence[Camera]) -> Dict[Tuple[int, int], str]:
    return {(cam.row_index, cam.col_index): cam.camera_id for cam in cameras}


def nearest_camera_id(cameras: Sequence[Camera], x_ft: float, y_ft: float) -> str:
    best = min(
        cameras,
        key=lambda cam: (cam.x_center_ft - x_ft) ** 2 + (cam.y_center_ft - y_ft) ** 2,
    )
    return best.camera_id


def tag_camera_ids_for_board(
    board: Board,
    cfg: Config,
    camera_lookup: Dict[Tuple[int, int], str],
    cameras: Sequence[Camera],
) -> List[str]:
    # Tag order: top-left, top-right, bottom-left, bottom-right
    neighbor_indices = [
        (board.row_index + 1, board.col_index),
        (board.row_index + 1, board.col_index + 1),
        (board.row_index, board.col_index),
        (board.row_index, board.col_index + 1),
    ]
    fallback_points = [
        (board.x_left_ft, board.y_bottom_ft + cfg.board_height_ft),  # top-left
        (board.x_left_ft + cfg.board_width_ft, board.y_bottom_ft + cfg.board_height_ft),  # top-right
        (board.x_left_ft, board.y_bottom_ft),  # bottom-left
        (board.x_left_ft + cfg.board_width_ft, board.y_bottom_ft),  # bottom-right
    ]

    ids: List[str] = []
    for (ri, ci), (fx, fy) in zip(neighbor_indices, fallback_points):
        cam_id = camera_lookup.get((ri, ci))
        if cam_id is None:
            cam_id = nearest_camera_id(cameras, fx, fy)
        ids.append(cam_id)
    return ids


def render_board_figure(
    board: Board,
    tag_images: Sequence[Image.Image],
    tag_camera_ids: Sequence[str],
    cfg: Config,
    page_size_in: Tuple[float, float],
) -> plt.Figure:
    fig = plt.figure(figsize=page_size_in, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    page_w, page_h = page_size_in
    ax.set_facecolor("white")
    ax.set_xlim(0, page_w)
    ax.set_ylim(0, page_h)
    ax.axis("off")

    header_h_in = cfg.header_height_in
    footer_h_in = cfg.footer_height_in
    margin_in = cfg.board_inner_margin_in
    gap_in = cfg.tag_gap_in

    avail_w = page_w - 2.0 * margin_in - gap_in
    avail_h = page_h - header_h_in - footer_h_in - 2.0 * margin_in - gap_in
    if avail_w <= 0 or avail_h <= 0:
        raise ValueError(
            "Board page is too small for the selected layout margins and header/footer."
        )
    max_fit_tag_size_in = min(avail_w / 2.0, avail_h / 2.0)
    if cfg.tag_size_in is not None:
        tag_size_in = cfg.tag_size_in
        if tag_size_in > max_fit_tag_size_in:
            raise ValueError(
                f"Requested tag_size_in={tag_size_in:.2f} in does not fit fixed board canvas. "
                f"Maximum fit size is {max_fit_tag_size_in:.2f} in for current margins/layout."
            )
    else:
        tag_size_in = max_fit_tag_size_in

    if tag_size_in < cfg.min_tag_size_in:
        raise ValueError(
            f"Computed tag size {tag_size_in:.2f} in is below min_tag_size_in={cfg.min_tag_size_in:.2f} in."
        )

    # Spread tags to the available corners for maximum baseline in camera views.
    # Keep at least requested gap/margins, and use all additional free space as separation.
    x_left = margin_in
    x_right = page_w - margin_in - tag_size_in
    y_bottom = footer_h_in + margin_in
    y_top = page_h - header_h_in - margin_in - tag_size_in
    gap_x = x_right - x_left - tag_size_in
    gap_y = y_top - y_bottom - tag_size_in

    if gap_x < gap_in - 1e-9 or gap_y < gap_in - 1e-9:
        raise ValueError(
            "Layout gap became smaller than requested tag_gap_in. "
            "Reduce tag_size_in or margins."
        )

    # Board outline and lightweight measurement aids.
    ax.add_patch(Rectangle((0, 0), page_w, page_h, fill=False, lw=1.4, ec="#222222"))
    draw_edge_rulers(ax, page_w, page_h, safe_x_clearance=x_left, safe_y_clearance=y_bottom)
    ax.plot([page_w / 2.0, page_w / 2.0], [0, page_h], ls="--", lw=0.8, color="#a0a0a0")
    ax.plot([0, page_w], [page_h / 2.0, page_h / 2.0], ls="--", lw=0.8, color="#a0a0a0")
    ax.text(
        page_w / 2.0 + 0.12,
        page_h / 2.0 + 0.12,
        "Canvas center",
        fontsize=5,
        color="#666666",
        ha="left",
        va="bottom",
    )

    # Prominent board identity + coordinate callout for field handling.
    ax.text(page_w / 2.0, page_h / 2.0 + 1.05, f"BOARD {board.board_id}", ha="center", va="center", fontsize=44, fontweight="bold")
    ax.text(
        page_w / 2.0,
        page_h / 2.0 + 0.30,
        f"LL CORNER: X={board.x_left_ft:.1f} ft, Y={board.y_bottom_ft:.1f} ft",
        ha="center",
        va="center",
        fontsize=24,
        fontweight="bold",
    )
    ax.text(
        page_w / 2.0,
        page_h / 2.0 - 0.20,
        f"GRID r{board.row_index + 1} c{board.col_index + 1}",
        ha="center",
        va="center",
        fontsize=16,
    )

    # 2x2 tag slots in inch units.
    slots = [
        (x_left, y_top, tag_size_in, tag_size_in),      # top-left
        (x_right, y_top, tag_size_in, tag_size_in),     # top-right
        (x_left, y_bottom, tag_size_in, tag_size_in),   # bottom-left
        (x_right, y_bottom, tag_size_in, tag_size_in),  # bottom-right
    ]
    for idx, (tag_image, (x, y, w, h)) in enumerate(zip(tag_images, slots)):
        ax.imshow(
            np.array(tag_image),
            cmap="gray",
            interpolation="nearest",
            extent=(x, x + w, y, y + h),
            origin="upper",
        )
        ax.add_patch(Rectangle((x, y), w, h, fill=False, lw=1.2, ec="black"))
        id_y = y - 0.10
        id_va = "top"
        cam_y = y - 0.48
        cam_va = "top"
        # For lower row tags, place labels above the tag.
        if idx >= 2:
            id_y = y + h + 0.32
            id_va = "bottom"
            cam_y = y + h + 0.06
            cam_va = "bottom"

        ax.text(
            x + w / 2.0,
            id_y,
            f"ID {board.tag_ids[idx]}",
            ha="center",
            va=id_va,
            fontsize=28,
            fontweight="bold",
        )
        ax.text(
            x + w / 2.0,
            cam_y,
            f"near {tag_camera_ids[idx]}",
            ha="center",
            va=cam_va,
            fontsize=cfg.board_near_camera_fontsize,
            fontweight="bold",
            color="#333333",
        )

    # Dimension cues
    # Keep details in the center gap area so they never overlay tag graphics.
    details_x = x_left + tag_size_in + 0.18
    ax.text(
        details_x,
        page_h / 2.0,
        (
            f"Tag={tag_size_in:.2f}in\n"
            f"GapX={gap_x:.2f}in\n"
            f"GapY={gap_y:.2f}in\n"
            f"Edge margin={margin_in:.2f}in"
        ),
        ha="left",
        va="center",
        fontsize=8,
        color="#444444",
        bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "#999999", "alpha": 0.8},
    )

    # Small arrows showing separation distance between tag centers.
    cxl = x_left + tag_size_in / 2.0
    cxr = x_right + tag_size_in / 2.0
    cyb = y_bottom + tag_size_in / 2.0
    cyt = y_top + tag_size_in / 2.0
    draw_dimension_line(
        ax,
        x0=cxl,
        y0=0.55,
        x1=cxr,
        y1=0.55,
        label=f"{(cxr - cxl):.2f} in tag pitch",
        text_x=(cxl + cxr) / 2.0,
        text_y=0.82,
    )
    draw_dimension_line(
        ax,
        x0=page_w - 0.58,
        y0=cyb,
        x1=page_w - 0.58,
        y1=cyt,
        label=f"{(cyt - cyb):.2f} in",
        text_x=page_w - 0.70,
        text_y=(cyb + cyt) / 2.0,
        rotation=90,
    )
    draw_dimension_line(
        ax,
        x0=0.6,
        y0=0.30,
        x1=page_w - 0.6,
        y1=0.30,
        label=f"{page_w:.1f} in board width",
        text_x=page_w / 2.0,
        text_y=0.12,
    )
    draw_dimension_line(
        ax,
        x0=0.30,
        y0=0.6,
        x1=0.30,
        y1=page_h - 0.6,
        label=f"{page_h:.1f} in board height",
        text_x=0.18,
        text_y=page_h / 2.0,
        rotation=90,
    )

    # Real-world quick-check scale bars in center gap.
    h_scale = max(2.0, min(6.0, gap_x - 0.8))
    v_scale = max(2.0, min(6.0, gap_y - 0.8))
    draw_scale_bar(
        ax,
        x0=page_w / 2.0 - h_scale / 2.0,
        y0=page_h / 2.0 - 2.2,
        length_in=h_scale,
        label=f"{h_scale:.1f} in reference",
        vertical=False,
    )
    draw_scale_bar(
        ax,
        x0=page_w / 2.0 - 3.4,
        y0=page_h / 2.0 - v_scale / 2.0,
        length_in=v_scale,
        label=f"{v_scale:.1f} in",
        vertical=True,
    )

    ax.annotate(
        "",
        xy=(page_w / 2.0 + 3.4, page_h / 2.0 - 0.20),
        xytext=(page_w / 2.0 + 3.4, page_h / 2.0 - 1.20),
        arrowprops={"arrowstyle": "-|>", "lw": 2.0, "color": "black"},
    )
    ax.text(
        page_w / 2.0 + 3.4,
        page_h / 2.0 - 0.05,
        "TOP / +Y",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
    )
    ax.text(
        page_w / 2.0,
        page_h / 2.0 - 0.80,
        (
            "Place board lower-left corner at listed coordinate. "
            f"Tag size = {tag_size_in:.2f} in"
        ),
        ha="center",
        va="bottom",
        fontsize=10,
        fontweight="bold",
    )
    return fig


def save_board_files(
    board: Board,
    cfg: Config,
    board_dir: Path,
    tiled_dir: Path,
    cameras: Sequence[Camera],
    camera_lookup: Dict[Tuple[int, int], str],
    combined_pdf: PdfPages | None = None,
) -> Tuple[Path, Path]:
    tag_images = [
        generate_apriltag_image(cfg.april_family, tag_id, size_px=900, strict_apriltag=cfg.strict_apriltag)
        for tag_id in board.tag_ids
    ]
    tag_camera_ids = tag_camera_ids_for_board(board, cfg, camera_lookup, cameras)

    board_page_size_in = fixed_board_canvas_size_in(cfg)
    figure = render_board_figure(board, tag_images, tag_camera_ids, cfg, board_page_size_in)

    pdf_path = board_dir / f"{board.board_id}.pdf"
    png_path = board_dir / f"{board.board_id}.png"

    figure.savefig(pdf_path, format="pdf")
    figure.savefig(png_path, format="png", dpi=cfg.board_png_dpi)
    if combined_pdf is not None:
        combined_pdf.savefig(figure)
    plt.close(figure)

    if cfg.tiled_output:
        full_board_size_in = fixed_board_canvas_size_in(cfg)
        poster_fig = render_board_figure(board, tag_images, tag_camera_ids, cfg, full_board_size_in)
        poster_png = tiled_dir / f"{board.board_id}_poster.png"
        poster_fig.savefig(poster_png, format="png", dpi=cfg.tile_dpi)
        plt.close(poster_fig)

        tiled_pdf = tiled_dir / f"{board.board_id}_tiled.pdf"
        make_tiled_pdf(
            image_path=poster_png,
            output_pdf=tiled_pdf,
            page_size_in=page_size_inches(
                cfg.tile_page_size, cfg.tile_page_width_in, cfg.tile_page_height_in
            ),
            dpi=cfg.tile_dpi,
            overlap_in=cfg.tile_overlap_in,
        )

    return pdf_path, png_path


def make_tiled_pdf(
    image_path: Path,
    output_pdf: Path,
    page_size_in: Tuple[float, float],
    dpi: int,
    overlap_in: float,
) -> None:
    image = Image.open(image_path).convert("RGB")
    page_w_px = int(round(page_size_in[0] * dpi))
    page_h_px = int(round(page_size_in[1] * dpi))
    overlap_px = int(round(overlap_in * dpi))

    if page_w_px <= 0 or page_h_px <= 0:
        raise ValueError("Tile page dimensions must be positive.")
    if overlap_px >= page_w_px or overlap_px >= page_h_px:
        raise ValueError("tile_overlap_in is too large for the selected tile page size.")

    step_x = max(1, page_w_px - overlap_px)
    step_y = max(1, page_h_px - overlap_px)

    w, h = image.size
    tiles: List[Image.Image] = []
    for y0 in range(0, h, step_y):
        for x0 in range(0, w, step_x):
            x1 = min(x0 + page_w_px, w)
            y1 = min(y0 + page_h_px, h)
            crop = image.crop((x0, y0, x1, y1))
            tile = Image.new("RGB", (page_w_px, page_h_px), color="white")
            tile.paste(crop, (0, 0))
            tiles.append(tile)
            if x1 == w and y1 == h:
                break
        if y1 == h:
            break

    if not tiles:
        raise RuntimeError(f"No tiles generated for {image_path}.")
    tiles[0].save(output_pdf, save_all=True, append_images=tiles[1:])


def unique_sorted(values: Sequence[float], tol: float = 1e-6) -> List[float]:
    out: List[float] = []
    for value in sorted(values):
        if not out or abs(value - out[-1]) > tol:
            out.append(value)
    return out


def draw_global_plan(
    cfg: Config,
    cameras: Sequence[Camera],
    boards: Sequence[Board],
    output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_aspect("equal", adjustable="box")

    # Field boundary
    ax.add_patch(
        Rectangle(
            (0, 0),
            cfg.field_width_ft,
            cfg.field_height_ft,
            fill=False,
            lw=2.2,
            ec="black",
            label="Field boundary",
        )
    )

    # Camera coverage rectangles
    for cam in cameras:
        ax.add_patch(
            Rectangle(
                (cam.x_min_ft, cam.y_min_ft),
                cfg.cam_width_ft,
                cfg.cam_height_ft,
                fill=False,
                lw=0.9,
                ec="#1f77b4",
                alpha=0.45,
            )
        )
        ax.plot(cam.x_center_ft, cam.y_center_ft, marker="o", color="#1f77b4", markersize=3.8)
        ax.text(
            cam.x_center_ft,
            cam.y_center_ft,
            cam.camera_id,
            fontsize=cfg.plan_camera_label_fontsize,
            color="#0d4f8b",
            fontweight="bold",
        )

    # Board rectangles (green boxes) sized by board_width_ft x board_height_ft.
    for board in boards:
        ax.add_patch(
            Rectangle(
                (board.x_left_ft, board.y_bottom_ft),
                cfg.board_width_ft,
                cfg.board_height_ft,
                fill=False,
                lw=1.4,
                ec="green",
            )
        )
        ax.plot(board.x_left_ft, board.y_bottom_ft, marker="o", color="green", markersize=3)
        ax.text(
            board.x_left_ft + 0.08,
            board.y_bottom_ft + cfg.board_height_ft + 0.08,
            f"{board.board_id} ({board.x_left_ft:.1f},{board.y_bottom_ft:.1f})",
            fontsize=7,
            color="darkgreen",
        )

    x_margin = max(1.0, 0.03 * cfg.field_width_ft)
    y_margin = max(1.0, 0.10 * cfg.field_height_ft)
    ax.set_xlim(-x_margin, cfg.field_width_ft + x_margin)
    ax.set_ylim(-y_margin, cfg.field_height_ft + y_margin)

    if cfg.plan_line_labels:
        x_lines = unique_sorted(
            [0.0, cfg.field_width_ft]
            + [cam.x_min_ft for cam in cameras]
            + [cam.x_max_ft for cam in cameras]
        )
        y_lines = unique_sorted(
            [0.0, cfg.field_height_ft]
            + [cam.y_min_ft for cam in cameras]
            + [cam.y_max_ft for cam in cameras]
        )
        fmt = f"{{:.{cfg.plan_line_decimals}f}}"

        for x in x_lines:
            ax.axvline(x, color="#777777", lw=0.5, alpha=0.25, zorder=0)
            ax.text(
                x,
                -y_margin * 0.55,
                fmt.format(x),
                fontsize=cfg.plan_line_label_fontsize,
                rotation=90,
                ha="center",
                va="top",
                color="#555555",
                clip_on=False,
            )

        for y in y_lines:
            ax.axhline(y, color="#777777", lw=0.5, alpha=0.25, zorder=0)
            ax.text(
                -x_margin * 0.10,
                y,
                fmt.format(y),
                fontsize=cfg.plan_line_label_fontsize,
                ha="right",
                va="center",
                color="#555555",
                clip_on=False,
            )

    ax.set_xlabel("X (ft) [field width axis]")
    ax.set_ylabel("Y (ft) [field height axis]")
    ax.set_title(
        "Camera Mesh and Board Placement Plan\n"
        "Origin: bottom-left, X rightward, Y upward"
    )
    ax.grid(True, alpha=0.3)

    pdf_path = output_dir / "camera_layout_plan.pdf"
    png_path = output_dir / "camera_layout_plan.png"
    fig.savefig(pdf_path, format="pdf", bbox_inches="tight")
    fig.savefig(png_path, format="png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def write_camera_manifest(cameras: Sequence[Camera], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "camera_id",
                "row_index",
                "col_index",
                "x_center_ft",
                "y_center_ft",
                "x_min_ft",
                "x_max_ft",
                "y_min_ft",
                "y_max_ft",
            ]
        )
        for cam in cameras:
            writer.writerow(
                [
                    cam.camera_id,
                    cam.row_index,
                    cam.col_index,
                    round(cam.x_center_ft, 4),
                    round(cam.y_center_ft, 4),
                    round(cam.x_min_ft, 4),
                    round(cam.x_max_ft, 4),
                    round(cam.y_min_ft, 4),
                    round(cam.y_max_ft, 4),
                ]
            )


def write_board_manifest(boards: Sequence[Board], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "board_id",
                "x_left_ft",
                "y_bottom_ft",
                "install_row",
                "row_index",
                "col_index",
                "tag_ids",
            ]
        )
        for board in boards:
            writer.writerow(
                [
                    board.board_id,
                    round(board.x_left_ft, 4),
                    round(board.y_bottom_ft, 4),
                    board.row_index + 1,
                    board.row_index,
                    board.col_index,
                    ";".join(str(t) for t in board.tag_ids),
                ]
            )


def board_overlaps_camera(cam: Camera, board: Board, cfg: Config) -> bool:
    board_x_min = board.x_left_ft
    board_x_max = board.x_left_ft + cfg.board_width_ft
    board_y_min = board.y_bottom_ft
    board_y_max = board.y_bottom_ft + cfg.board_height_ft
    overlap_x = min(cam.x_max_ft, board_x_max) - max(cam.x_min_ft, board_x_min)
    overlap_y = min(cam.y_max_ft, board_y_max) - max(cam.y_min_ft, board_y_min)
    return overlap_x > 0 and overlap_y > 0


def build_visibility(
    cameras: Sequence[Camera], boards: Sequence[Board], cfg: Config
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    board_to_cameras: Dict[str, List[str]] = {}
    camera_to_boards: Dict[str, List[str]] = {cam.camera_id: [] for cam in cameras}

    for board in boards:
        visible_cameras = [
            cam.camera_id
            for cam in cameras
            if board_overlaps_camera(cam, board, cfg)
        ]
        board_to_cameras[board.board_id] = visible_cameras
        for cam_id in visible_cameras:
            camera_to_boards[cam_id].append(board.board_id)
    return board_to_cameras, camera_to_boards


def write_visibility_reports(
    board_to_cameras: Dict[str, List[str]],
    camera_to_boards: Dict[str, List[str]],
    output_dir: Path,
) -> None:
    board_path = output_dir / "visibility_boards.csv"
    with board_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["board_id", "visible_camera_count", "camera_ids"])
        for board_id in sorted(board_to_cameras.keys()):
            cams = board_to_cameras[board_id]
            writer.writerow([board_id, len(cams), ";".join(cams)])

    camera_path = output_dir / "visibility_cameras.csv"
    with camera_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["camera_id", "visible_board_count", "board_ids"])
        for camera_id in sorted(camera_to_boards.keys()):
            boards = camera_to_boards[camera_id]
            writer.writerow([camera_id, len(boards), ";".join(boards)])


def edge_camera_ids(cameras: Sequence[Camera], rows: int, cols: int) -> List[str]:
    edge_ids: List[str] = []
    for cam in cameras:
        if (
            cam.row_index == 0
            or cam.row_index == rows - 1
            or cam.col_index == 0
            or cam.col_index == cols - 1
        ):
            edge_ids.append(cam.camera_id)
    return edge_ids


def save_combined_board_pdf(board_png_paths: Sequence[Path], output_pdf: Path) -> None:
    # Deprecated by direct PdfPages generation in main().
    _ = board_png_paths
    _ = output_pdf


def write_board_manifest_pdf(boards: Sequence[Board], path: Path) -> None:
    boards_sorted = sorted(boards, key=lambda b: (b.row_index, b.col_index))
    lines_per_page = 26
    with PdfPages(path) as pdf:
        for page_start in range(0, len(boards_sorted), lines_per_page):
            page_boards = boards_sorted[page_start : page_start + lines_per_page]
            fig, ax = plt.subplots(figsize=(11, 8.5))
            fig.patch.set_facecolor("white")
            ax.axis("off")
            ax.text(
                0.5,
                0.97,
                "Board Manifest (Row Grouped)",
                ha="center",
                va="top",
                fontsize=18,
                fontweight="bold",
                transform=ax.transAxes,
            )
            y = 0.91
            last_row = None
            for board in page_boards:
                row_num = board.row_index + 1
                if row_num != last_row:
                    ax.text(
                        0.05,
                        y,
                        f"Row {row_num}",
                        ha="left",
                        va="top",
                        fontsize=12,
                        fontweight="bold",
                        transform=ax.transAxes,
                    )
                    y -= 0.035
                    last_row = row_num
                ax.text(
                    0.07,
                    y,
                    (
                        f"{board.board_id:>4} | LL=({board.x_left_ft:.1f}, {board.y_bottom_ft:.1f}) ft "
                        f"| tags={board.tag_ids[0]},{board.tag_ids[1]},{board.tag_ids[2]},{board.tag_ids[3]}"
                    ),
                    ha="left",
                    va="top",
                    fontsize=10,
                    transform=ax.transAxes,
                )
                y -= 0.028
            pdf.savefig(fig)
            plt.close(fig)


def ensure_output_dirs(base_dir: Path, tiled_output: bool) -> Tuple[Path, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    board_dir = base_dir / "boards"
    board_dir.mkdir(parents=True, exist_ok=True)
    tiled_dir = base_dir / "boards_tiled"
    if tiled_output:
        tiled_dir.mkdir(parents=True, exist_ok=True)
    return board_dir, tiled_dir


def print_summary(
    cfg: Config,
    x_axis: AxisMesh,
    y_axis: AxisMesh,
    num_boards: int,
) -> None:
    rows = len(y_axis.centers)
    cols = len(x_axis.centers)
    total_cameras = rows * cols
    total_tags = num_boards * cfg.tags_per_board
    print("=== Dry-Run Summary ===")
    print(f"Field size: {cfg.field_width_ft:.2f} ft x {cfg.field_height_ft:.2f} ft")
    print(f"Camera FOV: {cfg.cam_width_ft:.2f} ft x {cfg.cam_height_ft:.2f} ft")
    print(
        f"Requested overlap ratios: X={cfg.overlap_x_ratio:.3f}, "
        f"Y={cfg.overlap_y_ratio:.3f}"
    )
    print(
        f"Target overlap widths: X={cfg.target_overlap_x_ft:.3f} ft, "
        f"Y={cfg.target_overlap_y_ft:.3f} ft"
    )
    print(
        f"Actual overlap widths: X={x_axis.overlap_used_ft:.3f} ft, "
        f"Y={y_axis.overlap_used_ft:.3f} ft"
    )
    print(
        f"Actual overlap ratios: X={x_axis.effective_overlap_ratio:.3f}, "
        f"Y={y_axis.effective_overlap_ratio:.3f}"
    )
    print(
        f"Strides (target->used): X={x_axis.stride_target_ft:.3f}->{x_axis.stride_used_ft:.3f} ft, "
        f"Y={y_axis.stride_target_ft:.3f}->{y_axis.stride_used_ft:.3f} ft"
    )
    print(
        f"Boundary overflow margins X(L/R): {x_axis.left_margin_ft:.3f}/{x_axis.right_margin_ft:.3f} ft"
    )
    print(
        f"Boundary overflow margins Y(B/T): {y_axis.left_margin_ft:.3f}/{y_axis.right_margin_ft:.3f} ft"
    )
    print(
        f"Boundary margin policy: preferred={cfg.min_edge_coverage_ratio * 100:.1f}% of FOV, "
        f"hard minimum={cfg.min_edge_margin_ft:.3f} ft"
    )
    print(f"Coordinate snap step: {cfg.coord_step_ft:.3f} ft")
    print(f"Camera grid: rows={rows}, cols={cols}, total={total_cameras}")
    print(f"Board intersections: total boards={num_boards}")
    print(f"Total AprilTags: {total_tags}")
    print("=======================")


def main(argv: Sequence[str]) -> int:
    cfg = parse_args(argv)

    output_dir = cfg.output_dir.resolve()
    board_dir, tiled_dir = ensure_output_dirs(output_dir, cfg.tiled_output)

    cameras, x_axis, y_axis = build_cameras(cfg)
    boards = build_boards(cfg, x_axis.centers, y_axis.centers)

    rows = len(y_axis.centers)
    cols = len(x_axis.centers)
    print_summary(cfg, x_axis, y_axis, len(boards))

    validate_tag_uniqueness(boards)
    validate_board_coordinates(boards, cfg)

    draw_global_plan(cfg, cameras, boards, output_dir)
    write_camera_manifest(cameras, output_dir / "cameras_manifest.csv")
    write_board_manifest(boards, output_dir / "boards_manifest.csv")

    board_pdf_paths: List[Path] = []
    board_png_count = 0
    camera_lookup = build_camera_grid_lookup(cameras)
    combined_pdf_path = output_dir / "boards_combined.pdf"
    with PdfPages(combined_pdf_path) as combined_pdf:
        for board in boards:
            pdf_path, _png_path = save_board_files(
                board,
                cfg,
                board_dir,
                tiled_dir,
                cameras,
                camera_lookup,
                combined_pdf=combined_pdf,
            )
            board_pdf_paths.append(pdf_path)
            board_png_count += 1

    write_board_manifest_pdf(boards, output_dir / "boards_manifest.pdf")

    board_to_cameras, camera_to_boards = build_visibility(cameras, boards, cfg)
    write_visibility_reports(board_to_cameras, camera_to_boards, output_dir)

    edge_ids = edge_camera_ids(cameras, rows, cols)
    edge_without_boards = [cid for cid in edge_ids if len(camera_to_boards[cid]) == 0]
    if boards and edge_without_boards:
        print(
            "Warning: Some edge cameras do not overlap any board footprint: "
            + ", ".join(edge_without_boards),
            file=sys.stderr,
        )

    print(f"Output directory: {output_dir}")
    print(f"Saved {len(board_pdf_paths)} board PDFs and {board_png_count} board PNGs.")
    print(f"Combined board PDF pages: {len(boards)}")
    print("Main files:")
    print(f"- {output_dir / 'camera_layout_plan.pdf'}")
    print(f"- {output_dir / 'camera_layout_plan.png'}")
    print(f"- {output_dir / 'boards_manifest.csv'}")
    print(f"- {output_dir / 'boards_manifest.pdf'}")
    print(f"- {output_dir / 'cameras_manifest.csv'}")
    print(f"- {output_dir / 'visibility_boards.csv'}")
    print(f"- {output_dir / 'visibility_cameras.csv'}")
    print(f"- {combined_pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
