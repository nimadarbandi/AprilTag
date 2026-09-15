#!/usr/bin/env python3
"""
update_layout.py — Standalone layout plan re-renderer.

Reads cameras_manifest.csv and boards_manifest.csv from the output directory
and regenerates camera_layout_plan.pdf / .png without re-running the full
board-generation pipeline.  Camera centre coordinates and DVR/cabling overlays
are included by default.

Usage:
    python update_layout.py
    python update_layout.py --output-dir demo_output --field-width 96 --field-height 27
    python update_layout.py --no-dvr --no-coords --no-grid

To add more overlays in the future, write a new draw_*() function in the
"Overlay draw functions" section and call it inside render_layout().
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
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


@dataclass
class Board:
    board_id: str
    row_index: int
    col_index: int
    x_left_ft: float
    y_bottom_ft: float
    tag_ids: Tuple[int, ...]


# ── DVR assignments ───────────────────────────────────────────────────────────
# Edit here to change camera groupings, DVR border colours, or placement side.
# "side": "top"    → DVR placed above field
# "side": "bottom" → DVR placed below field

DVR_ASSIGNMENTS: Dict[str, dict] = {
    "DVR1": {
        "camera_ids": [
            "C01", "C02", "C03", "C04",
            "C09", "C10", "C11", "C12",
            "C19", "C20",
        ],
        "color": "#CC0000",   # red
        "side": "bottom",     # rows 0-2 are in lower field → DVR below
    },
    "DVR2": {
        "camera_ids": [
            "C05", "C06", "C07", "C08",
            "C13", "C14", "C15", "C16",
            "C23", "C24",
        ],
        "color": "#0055CC",   # vivid purple
        "side": "bottom",     # rows 0-2 are in lower field → DVR below
    },
    "DVR3": {
        "camera_ids": [
            "C33", "C34", "C35", "C36",
            "C25", "C26", "C27", "C28",
            "C17", "C18",
        ],
        "color": "#0055CC",   # blue
        "side": "top",        # rows 2-4 are in upper field → DVR above
    },
    "DVR4": {
        "camera_ids": [
            "C37", "C38", "C39", "C40",
            "C29", "C30", "C31", "C32",
            "C21", "C22",
        ],
        "color": "#CC0000",   # golden yellow (visible on light background)
        "side": "top",        # rows 2-4 are in upper field → DVR above
    },
}


# ── CSV loaders ───────────────────────────────────────────────────────────────

def load_cameras(path: Path) -> List[Camera]:
    cameras: List[Camera] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cameras.append(Camera(
                camera_id=row["camera_id"],
                row_index=int(row["row_index"]),
                col_index=int(row["col_index"]),
                x_center_ft=float(row["x_center_ft"]),
                y_center_ft=float(row["y_center_ft"]),
                x_min_ft=float(row["x_min_ft"]),
                x_max_ft=float(row["x_max_ft"]),
                y_min_ft=float(row["y_min_ft"]),
                y_max_ft=float(row["y_max_ft"]),
            ))
    return cameras


def load_boards(path: Path) -> List[Board]:
    boards: List[Board] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tag_ids = tuple(int(t) for t in row["tag_ids"].split(";"))
            boards.append(Board(
                board_id=row["board_id"],
                row_index=int(row["row_index"]),
                col_index=int(row["col_index"]),
                x_left_ft=float(row["x_left_ft"]),
                y_bottom_ft=float(row["y_bottom_ft"]),
                tag_ids=tag_ids,
            ))
    return boards


# ── Field inference ───────────────────────────────────────────────────────────

def infer_field_bounds(cameras: List[Camera]) -> Tuple[float, float]:
    """Estimate field width/height from symmetric camera margins.

    Assumes origin at (0, 0) and that the margin from each edge equals
    the first camera centre position, i.e. field_size = first_centre + last_centre.
    """
    x_centers = sorted(set(c.x_center_ft for c in cameras))
    y_centers = sorted(set(c.y_center_ft for c in cameras))
    return x_centers[0] + x_centers[-1], y_centers[0] + y_centers[-1]


def format_ft_in(value_ft: float) -> str:
    sign = "-" if value_ft < 0 else ""
    value_abs = abs(value_ft)
    feet = int(value_abs)
    inches = round((value_abs - feet) * 12.0)
    if inches == 12:
        feet += 1
        inches = 0
    return f"{sign}{feet}'{inches}\""


def compute_overlap_centers(cameras: List[Camera]) -> List[float]:
    """Return Y-centers of overlap bands between adjacent camera rows."""
    row_bounds: Dict[int, Tuple[float, float]] = {}
    for cam in cameras:
        if cam.row_index not in row_bounds:
            row_bounds[cam.row_index] = (cam.y_min_ft, cam.y_max_ft)
        else:
            rmin, rmax = row_bounds[cam.row_index]
            row_bounds[cam.row_index] = (min(rmin, cam.y_min_ft), max(rmax, cam.y_max_ft))

    overlap_centers: List[float] = []
    sorted_rows = sorted(row_bounds.keys())
    for i in range(len(sorted_rows) - 1):
        y0_min, y0_max = row_bounds[sorted_rows[i]]
        y1_min, y1_max = row_bounds[sorted_rows[i + 1]]
        ov_low = max(y0_min, y1_min)
        ov_high = min(y0_max, y1_max)
        if ov_high > ov_low:
            overlap_centers.append((ov_low + ov_high) / 2.0)
    return overlap_centers


def compute_aligned_board_bottoms(
    boards: List[Board],
    cameras: List[Camera],
    board_height: float,
) -> Dict[str, float]:
    """Snap each board vertically to nearest camera-row overlap center."""
    overlap_centers = compute_overlap_centers(cameras)
    y_bottom_by_board: Dict[str, float] = {}
    for board in boards:
        y_bottom = board.y_bottom_ft
        if overlap_centers:
            board_center_y = board.y_bottom_ft + board_height / 2.0
            target_center = min(overlap_centers, key=lambda c: abs(c - board_center_y))
            y_bottom = target_center - board_height / 2.0
        y_bottom_by_board[board.board_id] = y_bottom
    return y_bottom_by_board


# ── Overlay draw functions ────────────────────────────────────────────────────
# Each function adds one visual layer to the axes.
# Add new draw_*() functions here and call them from render_layout().

def draw_field_boundary(ax: plt.Axes, field_width: float, field_height: float) -> None:
    ax.add_patch(Rectangle(
        (0, 0), field_width, field_height,
        fill=False, lw=2.2, ec="black", label="Field boundary",
    ))


def draw_cameras(
    ax: plt.Axes,
    cameras: List[Camera],
    show_coords: bool = True,
    id_fontsize: int = 10,
    coord_fontsize: int = 6,
    camera_colors: Optional[Dict[str, str]] = None,
) -> None:
    if not cameras:
        return
    cam_w = cameras[0].x_max_ft - cameras[0].x_min_ft
    cam_h = cameras[0].y_max_ft - cameras[0].y_min_ft
    for cam in cameras:
        label_color = camera_colors.get(cam.camera_id, "#0d4f8b") if camera_colors else "#0d4f8b"
        ax.add_patch(Rectangle(
            (cam.x_min_ft, cam.y_min_ft), cam_w, cam_h,
            fill=False, lw=1.0, ec="#abb2ad", ls="--", alpha=0.85,
        ))
        ax.plot(cam.x_center_ft, cam.y_center_ft,
                marker="o", color=label_color, markersize=3.8)
        ax.text(
            cam.x_center_ft, cam.y_center_ft,
            cam.camera_id,
            fontsize=7, color=label_color, fontweight="bold",
            ha="center", va="bottom",
        )
        if show_coords:
            ax.annotate(
                f" ({format_ft_in(cam.x_center_ft)},{format_ft_in(cam.y_center_ft)})",
                (cam.x_center_ft, cam.y_center_ft),
                xytext=(9, 0),
                textcoords="offset points",
                ha="left",
                va="bottom",
                fontsize=7,
                color="black",
                fontweight="normal",
            )


def draw_boards(
    ax: plt.Axes,
    boards: List[Board],
    cameras: List[Camera],
    board_width: float = 2.0,
    board_height: float = 2.0,
) -> None:
    y_bottom_by_board = compute_aligned_board_bottoms(boards, cameras, board_height)

    for board in boards:
        y_bottom = y_bottom_by_board[board.board_id]

        ax.add_patch(Rectangle(
            (board.x_left_ft, y_bottom), board_width, board_height,
            fill=False, lw=1.4, ec="black",
        ))
        ax.plot(board.x_left_ft, y_bottom,
                marker="o", color="black", markersize=3)
        ax.text(
            board.x_left_ft + 0.08,
            y_bottom - 0.08,
            f"{board.board_id} ({format_ft_in(board.x_left_ft)},{format_ft_in(y_bottom)})",
            fontsize=7, color="black", va="top",
        )


def draw_string_lines(
    ax: plt.Axes,
    boards: List[Board],
    cameras: List[Camera],
    field_width: float,
    field_height: float,
    board_height: float = 2.0,
) -> None:
    """Light green dotted string lines used for anchor positioning."""
    if not boards:
        return
    y_bottom_by_board = compute_aligned_board_bottoms(boards, cameras, board_height)
    x_strings = sorted({b.x_left_ft for b in boards})
    y_strings = sorted({y_bottom_by_board[b.board_id] for b in boards})
    string_color = "#39FF14"  # high-intensity light green

    for x in x_strings:
        ax.plot(
            [x, x], [0.0, field_height],
            color=string_color, lw=1.8, ls=":", alpha=1.0, zorder=0.8,
        )
        # String X measurement label inside barn wall (bottom-inside).
        ax.text(
            x,
            0.35,
            format_ft_in(x),
            fontsize=7.5,
            fontweight="bold",
            ha="center",
            va="bottom",
            color="black",
            zorder=1.2,
            bbox={"boxstyle": "round,pad=0.10", "fc": "white", "ec": string_color, "alpha": 0.85},
        )
    for y in y_strings:
        ax.plot(
            [0.0, field_width], [y, y],
            color=string_color, lw=1.8, ls=":", alpha=1.0, zorder=0.8,
        )
        # String Y measurement label inside barn wall (left-inside).
        ax.text(
            0.45,
            y,
            format_ft_in(y),
            fontsize=7.5,
            fontweight="bold",
            ha="left",
            va="center",
            color="black",
            zorder=1.2,
            bbox={"boxstyle": "round,pad=0.10", "fc": "white", "ec": string_color, "alpha": 0.85},
        )


def draw_camera_position_lines(
    ax: plt.Axes,
    cameras: List[Camera],
    field_width: float,
    field_height: float,
) -> None:
    """Camera-center reference lines + inside-wall measurements."""
    if not cameras:
        return

    cam_color = "#D8EF0A"  # distinct from string green
    x_centers = sorted({c.x_center_ft for c in cameras})
    y_centers = sorted({c.y_center_ft for c in cameras})

    for x in x_centers:
        ax.plot(
            [x, x], [0.0, field_height],
            color=cam_color, lw=1.2, ls="--", alpha=0.95, zorder=0.7,
        )
        # Camera X measurement label inside top wall.
        ax.text(
            x,
            field_height - 0.35,
            format_ft_in(x),
            fontsize=7.0,
            fontweight="bold",
            ha="center",
            va="top",
            color="black",
            zorder=1.15,
            bbox={"boxstyle": "round,pad=0.10", "fc": "white", "ec": cam_color, "alpha": 0.85},
        )

    for y in y_centers:
        ax.plot(
            [0.0, field_width], [y, y],
            color=cam_color, lw=1.2, ls="--", alpha=0.95, zorder=0.7,
        )
        # Camera Y measurement label inside right wall.
        ax.text(
            field_width - 0.45,
            y,
            format_ft_in(y),
            fontsize=7.0,
            fontweight="bold",
            ha="right",
            va="center",
            color="black",
            zorder=1.15,
            bbox={"boxstyle": "round,pad=0.10", "fc": "white", "ec": cam_color, "alpha": 0.85},
        )


def draw_grid_lines(
    ax: plt.Axes,
    cameras: List[Camera],
    field_width: float,
    field_height: float,
    x_margin: float,
    y_margin: float,
    fontsize: int = 6,
    decimals: int = 1,
) -> None:
    def _unique(vals: list, tol: float = 1e-6) -> list:
        result: list = []
        for v in sorted(vals):
            if not result or abs(v - result[-1]) > tol:
                result.append(v)
        return result

    x_lines = _unique([0.0, field_width]
                      + [c.x_min_ft for c in cameras]
                      + [c.x_max_ft for c in cameras])
    y_lines = _unique([0.0, field_height]
                      + [c.y_min_ft for c in cameras]
                      + [c.y_max_ft for c in cameras])

    for x in x_lines:
        ax.axvline(x, color="#b9c0bb", lw=0.8, ls="--", alpha=0.55, zorder=0)
        ax.text(x, -y_margin * 0.55, format_ft_in(x),
                fontsize=fontsize, rotation=90,
                ha="center", va="top", color="black", clip_on=False)
    for y in y_lines:
        ax.axhline(y, color="#b9c0bb", lw=0.8, ls="--", alpha=0.55, zorder=0)
        ax.text(-x_margin * 0.10, y, format_ft_in(y),
                fontsize=fontsize,
                ha="right", va="center", color="black", clip_on=False)


def draw_dvrs_and_cabling(
    ax: plt.Axes,
    cameras: List[Camera],
    field_height: float,
    dvr_assignments: Dict[str, dict],
    dvr_offset_ft: float = 6.0,
    dvr_width_ft: float = 8.0,
    dvr_height_ft: float = 2.0,
) -> None:
    """10 cables exit each DVR from the back edge, then split left/right.

    Ports are placed on the back side of each DVR (farthest side from cameras).
    Cameras are split into left/right groups and routes are distributed by row
    with small offsets to reduce cable overlap.
    """
    cam_lookup = {c.camera_id: c for c in cameras}

    def _spaced(start: float, end: float, n: int) -> List[float]:
        if n <= 0:
            return []
        span = end - start
        return [start + (i + 0.5) / n * span for i in range(n)]

    # ── Compute DVR centre positions from camera centroids ────────────────────
    dvr_pos: Dict[str, Tuple[float, float]] = {}
    for dvr_id, info in dvr_assignments.items():
        cams = [cam_lookup[cid] for cid in info["camera_ids"] if cid in cam_lookup]
        if not cams:
            continue
        cx = sum(c.x_center_ft for c in cams) / len(cams)
        cy = (field_height + dvr_offset_ft) if info["side"] == "top" else -dvr_offset_ft
        dvr_pos[dvr_id] = (cx, cy)

    # ── Cables radiate FROM the DVR to each camera ────────────────────────────
    for dvr_id, info in dvr_assignments.items():
        if dvr_id not in dvr_pos:
            continue
        dvr_x, dvr_y = dvr_pos[dvr_id]
        color = info["color"]
        cam_ids = info["camera_ids"]

        box_left = dvr_x - dvr_width_ft / 2
        box_right = dvr_x + dvr_width_ft / 2
        box_top  = dvr_y + dvr_height_ft / 2
        box_bot  = dvr_y - dvr_height_ft / 2

        cams_for_dvr = [cam_lookup[cid] for cid in cam_ids if cid in cam_lookup]
        if not cams_for_dvr:
            continue

        left_cams = sorted(
            [c for c in cams_for_dvr if c.x_center_ft <= dvr_x],
            key=lambda c: (c.y_center_ft, c.x_center_ft),
        )
        right_cams = sorted(
            [c for c in cams_for_dvr if c.x_center_ft > dvr_x],
            key=lambda c: (c.y_center_ft, c.x_center_ft),
        )

        # Back side is opposite the camera-facing edge.
        back_edge_y = box_bot if info["side"] == "bottom" else box_top
        back_dir = -1.0 if info["side"] == "bottom" else 1.0
        stub_len = 0.55

        n_left = len(left_cams)
        n_right = len(right_cams)
        if n_left > 0 and n_right > 0:
            left_port_xs = _spaced(box_left, dvr_x, n_left)
            right_port_xs = _spaced(dvr_x, box_right, n_right)
        elif n_left > 0:
            left_port_xs = _spaced(box_left, box_right, n_left)
            right_port_xs = []
        else:
            left_port_xs = []
            right_port_xs = _spaced(box_left, box_right, n_right)

        # Assign ports: left-group cameras use left-half ports, right-group cameras use right-half ports.
        port_by_camera: Dict[str, Tuple[float, float, str]] = {}
        for cam, px in zip(left_cams, left_port_xs):
            port_by_camera[cam.camera_id] = (px, back_edge_y, "left")
        for cam, px in zip(right_cams, right_port_xs):
            port_by_camera[cam.camera_id] = (px, back_edge_y, "right")

        # Row-based lane Y values with tiny same-row offsets to avoid overlap.
        lane_y_by_camera: Dict[str, float] = {}
        for side_cams in (left_cams, right_cams):
            rows: Dict[float, List[Camera]] = {}
            for cam in side_cams:
                rows.setdefault(cam.y_center_ft, []).append(cam)
            for row_y, row_cams in rows.items():
                row_cams.sort(key=lambda c: c.x_center_ft)
                m = len(row_cams)
                for i, cam in enumerate(row_cams):
                    delta = 0.18 * (i - (m - 1) / 2.0)
                    lane_y_by_camera[cam.camera_id] = row_y + back_dir * delta

        # For same camera column on one side, use tiny x offsets to prevent shared vertical segments.
        drop_x_by_camera: Dict[str, float] = {}
        for side_cams in (left_cams, right_cams):
            cols: Dict[float, List[Camera]] = {}
            for cam in side_cams:
                cols.setdefault(cam.x_center_ft, []).append(cam)
            for col_x, col_cams in cols.items():
                col_cams.sort(key=lambda c: c.y_center_ft)
                m = len(col_cams)
                for i, cam in enumerate(col_cams):
                    delta = 0.14 * (i - (m - 1) / 2.0)
                    drop_x_by_camera[cam.camera_id] = col_x + delta

        cable_specs = []
        for cid in cam_ids:
            if cid not in cam_lookup or cid not in port_by_camera:
                continue
            cam = cam_lookup[cid]
            port_x, port_y, cam_side = port_by_camera[cid]
            stub_x = port_x
            stub_y = port_y + back_dir * stub_len
            label_x = port_x
            label_y = port_y + back_dir * 0.30
            va = "bottom" if back_dir > 0 else "top"

            cable_specs.append({
                "cid": cid,
                "cam": cam,
                "cam_side": cam_side,
                "port_x": port_x,
                "port_y": port_y,
                "stub_x": stub_x,
                "stub_y": stub_y,
                "label_x": label_x,
                "label_y": label_y,
                "ha": "center",
                "va": va,
                "rot": 90,
                "lane_y": lane_y_by_camera[cid],
                "drop_x": drop_x_by_camera[cid],
            })

        for spec in cable_specs:
            # Short port stub keeps the "exit point" readable.
            ax.plot(
                [spec["port_x"], spec["stub_x"]],
                [spec["port_y"], spec["stub_y"]],
                color=color, lw=1.0, alpha=0.70, zorder=2,
            )

            cam_x = spec["cam"].x_center_ft
            cam_y = spec["cam"].y_center_ft
            lane_y = spec["lane_y"]
            drop_x = spec["drop_x"]
            route_segs = [
                (spec["stub_x"], spec["stub_y"], spec["stub_x"], lane_y),
                (spec["stub_x"], lane_y, drop_x, lane_y),
                (drop_x, lane_y, drop_x, cam_y),
                (drop_x, cam_y, cam_x, cam_y),
            ]
            for x1, y1, x2, y2 in route_segs:
                ax.plot(
                    [x1, x2],
                    [y1, y2],
                    color=color, lw=1.0, alpha=0.65, zorder=2,
                )

            # Camera ID label right where the cable exits the DVR box.
            ax.text(
                spec["label_x"], spec["label_y"], spec["cid"],
                fontsize=5.5, ha=spec["ha"], va=spec["va"],
                color=color, fontweight="bold",
                rotation=spec["rot"], zorder=7,
            )

    # ── DVR boxes (drawn above cables) ────────────────────────────────────────
    for dvr_id, info in dvr_assignments.items():
        if dvr_id not in dvr_pos:
            continue
        dvr_x, dvr_y = dvr_pos[dvr_id]
        color = info["color"]
        ax.add_patch(Rectangle(
            (dvr_x - dvr_width_ft / 2, dvr_y - dvr_height_ft / 2),
            dvr_width_ft, dvr_height_ft,
            facecolor="white", edgecolor=color, lw=2.5, zorder=5,
        ))
        ax.text(
            dvr_x, dvr_y, dvr_id,
            fontsize=9, fontweight="bold", ha="center", va="center",
            color=color, zorder=6,
        )

    # ── Legend ────────────────────────────────────────────────────────────────
    ax.legend(
        handles=[
            Line2D([0], [0], color=info["color"], lw=1.5, label=dvr_id)
            for dvr_id, info in dvr_assignments.items()
            if dvr_id in dvr_pos
        ],
        loc="lower left", fontsize=7, framealpha=0.85,
        title="DVR (coaxial)", title_fontsize=7,
    )


# ── Main renderer ─────────────────────────────────────────────────────────────

# Constants shared between render_layout and draw_dvrs_and_cabling
_DVR_OFFSET_FT = 6.0   # ft between field edge and DVR centre
_DVR_WIDTH_FT  = 8.0   # widened 2x to increase back-edge port spacing
_DVR_HEIGHT_FT = 2.0   # reduced height for cleaner port placement


def render_layout(
    cameras: List[Camera],
    boards: List[Board],
    output_dir: Path,
    field_width: Optional[float] = None,
    field_height: Optional[float] = None,
    show_camera_coords: bool = True,
    show_grid: bool = True,
    board_width: float = 2.0,
    board_height: float = 2.0,
    dvr_assignments: Optional[Dict[str, dict]] = None,
    layout_title: Optional[str] = None,
) -> None:
    fw, fh = infer_field_bounds(cameras)
    field_width  = field_width  if field_width  is not None else fw
    field_height = field_height if field_height is not None else fh

    # Axis limits and figure size depend on field + actual camera coverage extents.
    x_margin = max(1.0, 0.06 * field_width)
    y_margin = max(1.0, 0.10 * field_height)

    cam_x_min = min((c.x_min_ft for c in cameras), default=0.0)
    cam_x_max = max((c.x_max_ft for c in cameras), default=field_width)
    cam_y_min = min((c.y_min_ft for c in cameras), default=0.0)
    cam_y_max = max((c.y_max_ft for c in cameras), default=field_height)
    # Extra small padding keeps labels and outlines from touching the plot border.
    content_x_left = min(0.0, cam_x_min) - 0.6
    content_x_right = max(field_width, cam_x_max) + 0.6
    content_y_bottom = min(0.0, cam_y_min) - 0.4
    content_y_top = max(field_height, cam_y_max) + 0.4

    if dvr_assignments:
        dvr_outer = _DVR_OFFSET_FT + _DVR_HEIGHT_FT / 2 + 2.5
        y_bottom  = -dvr_outer
        y_top     = field_height + dvr_outer
        x_left    = min(content_x_left, -x_margin)
        x_right   = max(content_x_right, field_width + x_margin)
        figsize   = (18, 10)
    else:
        y_bottom = min(content_y_bottom, -y_margin)
        y_top    = max(content_y_top, field_height + y_margin)
        x_left   = min(content_x_left, -x_margin)
        x_right  = max(content_x_right, field_width + x_margin)
        figsize  = (16, 6)

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect("equal", adjustable="box")

    # Build camera→DVR-colour lookup so labels match cables
    camera_colors: Optional[Dict[str, str]] = None
    if dvr_assignments:
        camera_colors = {}
        for info in dvr_assignments.values():
            for cid in info["camera_ids"]:
                camera_colors[cid] = info["color"]

    # ── Overlays — add new draw_* calls here ──────────────────────────────────
    draw_field_boundary(ax, field_width, field_height)
    draw_string_lines(ax, boards, cameras, field_width, field_height, board_height=board_height)
    draw_camera_position_lines(ax, cameras, field_width, field_height)
    draw_cameras(ax, cameras, show_coords=show_camera_coords, camera_colors=camera_colors)
    draw_boards(ax, boards, cameras, board_width=board_width, board_height=board_height)

    ax.set_xlim(x_left, x_right)
    ax.set_ylim(y_bottom, y_top)

    if show_grid:
        draw_grid_lines(ax, cameras, field_width, field_height, x_margin, y_margin)

    if dvr_assignments:
        draw_dvrs_and_cabling(
            ax, cameras, field_height, dvr_assignments,
            dvr_offset_ft=_DVR_OFFSET_FT,
            dvr_width_ft=_DVR_WIDTH_FT,
            dvr_height_ft=_DVR_HEIGHT_FT,
        )
    # ─────────────────────────────────────────────────────────────────────────

    ax.set_xlabel("X (ft) [field width axis]")
    ax.set_ylabel("Y (ft) [field height axis]")
    if layout_title is None:
        layout_title = (
            "Camera Mesh and Board Placement Plan\n"
            "Origin: bottom-left, X rightward, Y upward"
        )
    ax.set_title(layout_title)
    ax.grid(True, color="#1f9d45", linestyle="--", linewidth=0.6, alpha=0.30)

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "camera_layout_plan.pdf"
    png_path = output_dir / "camera_layout_plan.png"
    fig.savefig(pdf_path, format="pdf", bbox_inches="tight")
    fig.savefig(png_path, format="png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Layout saved → {pdf_path}")
    print(f"Layout saved → {png_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Re-render camera layout plan from manifest CSVs."
    )
    p.add_argument(
        "--output-dir", default="demo_output",
        help="Directory containing manifest CSVs; layout files are written here too.",
    )
    p.add_argument(
        "--field-width", type=float, default=None,
        help="Field width in ft (auto-inferred from camera centres if omitted).",
    )
    p.add_argument(
        "--field-height", type=float, default=None,
        help="Field height in ft (auto-inferred from camera centres if omitted).",
    )
    p.add_argument(
        "--no-coords", action="store_true",
        help="Hide camera centre coordinate labels.",
    )
    p.add_argument(
        "--no-grid", action="store_true",
        help="Hide coordinate grid lines.",
    )
    p.add_argument(
        "--board-width", type=float, default=2.0,
        help="Board width in ft (default 2.0).",
    )
    p.add_argument(
        "--board-height", type=float, default=2.0,
        help="Board height in ft (default 2.0).",
    )
    p.add_argument(
        "--no-dvr", action="store_true",
        help="Hide DVR boxes and cabling overlay.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    out = Path(args.output_dir)
    cameras = load_cameras(out / "cameras_manifest.csv")
    boards  = load_boards(out  / "boards_manifest.csv")
    print(f"Loaded {len(cameras)} cameras, {len(boards)} boards from {out}")
    render_layout(
        cameras=cameras,
        boards=boards,
        output_dir=out,
        field_width=args.field_width,
        field_height=args.field_height,
        show_camera_coords=not args.no_coords,
        show_grid=not args.no_grid,
        board_width=args.board_width,
        board_height=args.board_height,
        dvr_assignments=None if args.no_dvr else DVR_ASSIGNMENTS,
    )


if __name__ == "__main__":
    main()
