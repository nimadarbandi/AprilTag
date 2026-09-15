#!/usr/bin/env python3
"""
Create a new camera/board layout plan for a new field while reusing printed boards
from demo_output as much as possible, and assign cameras to DVRs to reduce cable
distance.

This script never modifies demo_output or generate_camera_mesh_and_apriltag_boards.py.
It writes a new output folder with manifests and optional rendered layout.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


@dataclass
class CameraRec:
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
class BoardRec:
    board_id: str
    row_index: int
    col_index: int
    x_left_ft: float
    y_bottom_ft: float
    tag_ids: Tuple[int, ...]


@dataclass
class AxisLayout:
    centers: List[float]
    stride_ft: float
    overlap_ft: float
    left_margin_ft: float
    right_margin_ft: float


@dataclass
class PrintedBoard:
    board_id: str
    tag_ids: Tuple[int, ...]


def snap_to_step(value: float, step_ft: float) -> float:
    return round(value / step_ft) * step_ft


def ceil_to_step(value: float, step_ft: float) -> float:
    return math.ceil(value / step_ft) * step_ft


def compute_axis_fixed_count(
    field_span_ft: float,
    cam_span_ft: float,
    overlap_ratio: float,
    min_edge_coverage_ratio: float,
    min_edge_margin_ft: float,
    target_overlap_ft: float,
    coord_step_ft: float,
    count: int,
    axis_label: str,
) -> AxisLayout:
    if count <= 0:
        raise ValueError(f"{axis_label}: camera count must be >= 1.")
    if count == 1:
        center = snap_to_step(field_span_ft / 2.0, coord_step_ft)
        left_margin = cam_span_ft / 2.0 - center
        right_margin = center + cam_span_ft / 2.0 - field_span_ft
        if left_margin < min_edge_margin_ft or right_margin < min_edge_margin_ft:
            raise ValueError(
                f"{axis_label}: one camera cannot satisfy min_edge_margin_ft={min_edge_margin_ft:.2f}."
            )
        return AxisLayout(
            centers=[center],
            stride_ft=0.0,
            overlap_ft=0.0,
            left_margin_ft=left_margin,
            right_margin_ft=right_margin,
        )

    stride_target = cam_span_ft * (1.0 - overlap_ratio)
    preferred_margin_ft = cam_span_ft * min_edge_coverage_ratio
    max_stride_for_target = cam_span_ft - target_overlap_ft
    if max_stride_for_target < 0:
        raise ValueError(f"{axis_label}: target overlap exceeds camera span.")

    span_required = field_span_ft - cam_span_ft + 2.0 * min_edge_margin_ft
    stride_min = max(0.0, span_required / (count - 1))
    stride_min = ceil_to_step(stride_min, coord_step_ft)
    stride_max = snap_to_step(max_stride_for_target, coord_step_ft)
    if stride_min > stride_max + 1e-9:
        min_count = int(math.ceil(span_required / max(1e-9, max_stride_for_target))) + 1
        raise ValueError(
            f"{axis_label}: requested {count} cameras cannot satisfy target overlap "
            f"{target_overlap_ft:.2f} ft and min edge margin {min_edge_margin_ft:.2f} ft. "
            f"Need at least ~{min_count} cameras on this axis."
        )

    best: AxisLayout | None = None
    best_score = float("inf")
    tol = 1e-9
    kmax = int(max(0, round((stride_max - stride_min) / coord_step_ft))) + 1
    for k in range(kmax + 1):
        stride = stride_min + k * coord_step_ft
        if stride > stride_max + tol:
            continue
        x0_ideal = (field_span_ft - (count - 1) * stride) / 2.0
        x0 = snap_to_step(x0_ideal, coord_step_ft)
        centers = [x0 + i * stride for i in range(count)]

        left_margin = cam_span_ft / 2.0 - centers[0]
        right_margin = centers[-1] + cam_span_ft / 2.0 - field_span_ft
        if left_margin < -tol or right_margin < -tol:
            continue
        if left_margin + tol < min_edge_margin_ft or right_margin + tol < min_edge_margin_ft:
            continue

        overlap = cam_span_ft - stride
        if overlap + tol < target_overlap_ft:
            continue

        symmetry_delta = abs(left_margin - right_margin)
        preferred_shortfall = (
            max(0.0, preferred_margin_ft - left_margin)
            + max(0.0, preferred_margin_ft - right_margin)
        )
        score = (
            8.0 * abs(stride - stride_target)
            + 6.0 * symmetry_delta
            + 2.0 * abs(overlap - target_overlap_ft)
            + 1.5 * preferred_shortfall
        )
        if score < best_score:
            best_score = score
            best = AxisLayout(
                centers=centers,
                stride_ft=stride,
                overlap_ft=overlap,
                left_margin_ft=left_margin,
                right_margin_ft=right_margin,
            )

    if best is None:
        raise ValueError(f"{axis_label}: no valid axis solution for requested constraints.")
    return best


def compute_axis_auto_count(
    field_span_ft: float,
    cam_span_ft: float,
    overlap_ratio: float,
    min_edge_coverage_ratio: float,
    min_edge_margin_ft: float,
    target_overlap_ft: float,
    coord_step_ft: float,
    axis_label: str,
) -> AxisLayout:
    """Auto-select a camera count using original mesh behavior + constraints."""
    stride_target = cam_span_ft * (1.0 - overlap_ratio)

    if field_span_ft <= cam_span_ft:
        return compute_axis_fixed_count(
            field_span_ft=field_span_ft,
            cam_span_ft=cam_span_ft,
            overlap_ratio=overlap_ratio,
            min_edge_coverage_ratio=min_edge_coverage_ratio,
            min_edge_margin_ft=min_edge_margin_ft,
            target_overlap_ft=target_overlap_ft,
            coord_step_ft=coord_step_ft,
            count=1,
            axis_label=axis_label,
        )

    base_count = int(math.ceil((field_span_ft - cam_span_ft) / stride_target)) + 1
    candidate_counts = range(max(2, base_count - 2), base_count + 8)

    best: AxisLayout | None = None
    best_score = float("inf")
    for count in candidate_counts:
        try:
            layout = compute_axis_fixed_count(
                field_span_ft=field_span_ft,
                cam_span_ft=cam_span_ft,
                overlap_ratio=overlap_ratio,
                min_edge_coverage_ratio=min_edge_coverage_ratio,
                min_edge_margin_ft=min_edge_margin_ft,
                target_overlap_ft=target_overlap_ft,
                coord_step_ft=coord_step_ft,
                count=count,
                axis_label=axis_label,
            )
        except ValueError:
            continue
        # Prefer overlap close to target, stride close to ratio target, fewer cameras when ties.
        score = (
            8.0 * abs(layout.overlap_ft - target_overlap_ft)
            + 3.0 * abs(layout.stride_ft - stride_target)
            + 0.75 * count
        )
        if score < best_score:
            best_score = score
            best = layout

    if best is None:
        raise ValueError(
            f"{axis_label}: could not auto-build a valid mesh for requested constraints."
        )
    return best


def load_printed_boards(path: Path) -> List[PrintedBoard]:
    boards: List[PrintedBoard] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tag_ids = tuple(int(t) for t in row["tag_ids"].split(";"))
            boards.append(PrintedBoard(board_id=row["board_id"], tag_ids=tag_ids))
    boards.sort(key=lambda b: int(b.board_id[1:]))
    return boards


def build_cameras(
    field_width_ft: float,
    field_height_ft: float,
    cam_width_ft: float,
    cam_height_ft: float,
    x_centers: Sequence[float],
    y_centers: Sequence[float],
    numbering_order: str,
) -> List[CameraRec]:
    out: List[CameraRec] = []
    seq = 1
    if numbering_order == "vertical":
        rc_iter = ((r, c) for c in range(len(x_centers)) for r in range(len(y_centers)))
    elif numbering_order == "vertical_snake":
        rc_pairs: List[Tuple[int, int]] = []
        n_rows = len(y_centers)
        for c in range(len(x_centers)):
            if c % 2 == 0:
                rows = range(0, n_rows)          # down -> up
            else:
                rows = range(n_rows - 1, -1, -1) # up -> down
            for r in rows:
                rc_pairs.append((r, c))
        rc_iter = rc_pairs
    else:
        rc_iter = ((r, c) for r in range(len(y_centers)) for c in range(len(x_centers)))
    for r, c in rc_iter:
        yc = y_centers[r]
        xc = x_centers[c]
        out.append(
            CameraRec(
                camera_id=f"C{seq:02d}",
                row_index=r,
                col_index=c,
                x_center_ft=xc,
                y_center_ft=yc,
                x_min_ft=xc - cam_width_ft / 2.0,
                x_max_ft=xc + cam_width_ft / 2.0,
                y_min_ft=yc - cam_height_ft / 2.0,
                y_max_ft=yc + cam_height_ft / 2.0,
            )
        )
        seq += 1
    return out


def build_reused_boards(
    printed_boards: Sequence[PrintedBoard],
    x_centers: Sequence[float],
    y_centers: Sequence[float],
    board_width_ft: float,
    board_height_ft: float,
    coord_step_ft: float,
    board_offset_x_ft: float,
    board_offset_y_ft: float,
    field_width_ft: float,
    field_height_ft: float,
    placement_order: str,
) -> Tuple[List[BoardRec], int]:
    slots: List[Tuple[int, int, float, float]] = []
    x_left_max = max(0.0, field_width_ft - board_width_ft)
    y_bottom_max = max(0.0, field_height_ft - board_height_ft)

    if placement_order == "vertical":
        rc_iter = ((r, c) for c in range(len(x_centers) - 1) for r in range(len(y_centers) - 1))
    elif placement_order == "vertical_snake":
        rc_pairs: List[Tuple[int, int]] = []
        n_rows = len(y_centers) - 1
        for c in range(len(x_centers) - 1):
            if c % 2 == 0:
                rows = range(0, n_rows)          # down -> up
            else:
                rows = range(n_rows - 1, -1, -1) # up -> down
            for r in rows:
                rc_pairs.append((r, c))
        rc_iter = rc_pairs
    else:
        rc_iter = ((r, c) for r in range(len(y_centers) - 1) for c in range(len(x_centers) - 1))

    for r, c in rc_iter:
        y_raw = (y_centers[r] + y_centers[r + 1]) / 2.0 + board_offset_y_ft
        x_raw = (x_centers[c] + x_centers[c + 1]) / 2.0 + board_offset_x_ft
        x_left = snap_to_step(x_raw - board_width_ft / 2.0, coord_step_ft)
        y_bottom = snap_to_step(y_raw - board_height_ft / 2.0, coord_step_ft)
        x_left = float(min(max(0.0, x_left), x_left_max))
        y_bottom = float(min(max(0.0, y_bottom), y_bottom_max))
        slots.append((r, c, x_left, y_bottom))

    use_count = min(len(slots), len(printed_boards))
    boards: List[BoardRec] = []
    for idx in range(use_count):
        r, c, x_left, y_bottom = slots[idx]
        pb = printed_boards[idx]
        boards.append(
            BoardRec(
                board_id=pb.board_id,
                row_index=r,
                col_index=c,
                x_left_ft=x_left,
                y_bottom_ft=y_bottom,
                tag_ids=pb.tag_ids,
            )
        )
    return boards, len(slots)


def assign_cameras_to_dvrs(
    cameras: Sequence[CameraRec],
    num_dvrs: int,
    field_height_ft: float,
    max_cams_per_dvr: int,
) -> Dict[str, dict]:
    if num_dvrs <= 0:
        raise ValueError("num_dvrs must be > 0.")
    if num_dvrs > len(cameras):
        raise ValueError("num_dvrs cannot exceed number of cameras.")
    if max_cams_per_dvr <= 0:
        raise ValueError("max_cams_per_dvr must be > 0.")
    if len(cameras) > num_dvrs * max_cams_per_dvr:
        raise ValueError(
            f"Not enough DVR ports: cameras={len(cameras)} > num_dvrs*max_cams_per_dvr={num_dvrs * max_cams_per_dvr}."
        )

    # Contiguous-by-X assignment (dynamic programming) minimizes long cross-barn runs.
    cams_sorted = sorted(cameras, key=lambda c: (c.x_center_ft, c.y_center_ft, int(c.camera_id[1:])))
    n = len(cams_sorted)

    def segment_cost(i: int, j: int) -> float:
        # L1 cost to segment mean point (matches downstream DVR placement centroids).
        pts = cams_sorted[i:j + 1]
        mx = sum(c.x_center_ft for c in pts) / len(pts)
        my = sum(c.y_center_ft for c in pts) / len(pts)
        return sum(abs(c.x_center_ft - mx) + abs(c.y_center_ft - my) for c in pts)

    # Precompute costs for valid segment sizes only.
    cost = [[float("inf")] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, min(n, i + max_cams_per_dvr)):
            cost[i][j] = segment_cost(i, j)

    inf = float("inf")
    dp = [[inf] * (num_dvrs + 1) for _ in range(n + 1)]
    prv = [[-1] * (num_dvrs + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        for k in range(1, num_dvrs + 1):
            # previous split index p means segment p..i-1 belongs to DVR k
            p_min = max(0, i - max_cams_per_dvr)
            for p in range(p_min, i):
                if dp[p][k - 1] == inf:
                    continue
                seg_len = i - p
                # ensure enough remaining cameras for remaining dvrs (>=1 each)
                remaining_cams = n - i
                remaining_dvrs = num_dvrs - k
                if remaining_cams < remaining_dvrs:
                    continue
                v = dp[p][k - 1] + cost[p][i - 1]
                if v < dp[i][k]:
                    dp[i][k] = v
                    prv[i][k] = p

    if dp[n][num_dvrs] == inf:
        raise ValueError("Could not assign cameras to DVRs under port/capacity constraints.")

    groups_rev: List[Tuple[int, int]] = []
    i = n
    k = num_dvrs
    while k > 0:
        p = prv[i][k]
        if p < 0:
            raise RuntimeError("Internal error reconstructing DVR assignment.")
        groups_rev.append((p, i - 1))
        i = p
        k -= 1
    groups = list(reversed(groups_rev))

    colors = ["#CC0000", "#0055CC", "#009E73", "#D55E00", "#7F3C8D", "#0072B2", "#E69F00", "#C44E52"]
    result: Dict[str, dict] = {}
    for j, (a, b) in enumerate(groups):
        dvr_id = f"DVR{j + 1}"
        cam_members = cams_sorted[a:b + 1]
        cam_members.sort(key=lambda c: int(c.camera_id[1:]))
        mean_y = sum(c.y_center_ft for c in cam_members) / len(cam_members)
        side = "top" if mean_y >= field_height_ft / 2.0 else "bottom"
        result[dvr_id] = {
            "camera_ids": [c.camera_id for c in cam_members],
            "color": colors[j % len(colors)],
            "side": side,
        }
    return result


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan new layout while reusing printed demo_output boards.")
    p.add_argument("--printed_boards_csv", type=Path, default=Path("demo_output/boards_manifest.csv"))
    p.add_argument("--output_dir", type=Path, required=True)

    # Original-style arguments.
    p.add_argument("--field_width_ft", type=float, required=True)
    p.add_argument("--field_height_ft", type=float, required=True)
    p.add_argument("--cam_width_ft", type=float, required=True)
    p.add_argument("--cam_height_ft", type=float, required=True)
    p.add_argument("--overlap_x_ratio", type=float, default=0.16)
    p.add_argument("--overlap_y_ratio", type=float, default=0.20)
    p.add_argument("--min_edge_coverage_ratio", type=float, default=0.10)
    p.add_argument("--min_edge_margin_ft", type=float, default=1.0)
    p.add_argument("--target_overlap_x_ft", type=float, required=True)
    p.add_argument("--target_overlap_y_ft", type=float, required=True)
    p.add_argument("--coord_step_ft", type=float, default=0.5)
    p.add_argument("--board_width_ft", type=float, default=2.0)
    p.add_argument("--board_height_ft", type=float, default=2.0)
    p.add_argument("--board_offset_x_ft", type=float, default=0.0)
    p.add_argument("--board_offset_y_ft", type=float, default=0.0)

    # Optional forced camera grid. If omitted, planner auto-suggests.
    p.add_argument("--num_cam_cols", type=int, default=None)
    p.add_argument("--num_cam_rows", type=int, default=None)

    # DVR planning.
    p.add_argument("--num_dvrs", type=int, required=True)
    p.add_argument("--max_cams_per_dvr", type=int, default=10)
    p.add_argument(
        "--numbering_order",
        choices=["horizontal", "vertical", "vertical_snake"],
        default="horizontal",
        help="Camera numbering order and board placement sequencing.",
    )

    # Compatibility args accepted but unused by this planner.
    p.add_argument("--tag_size_in", type=float, default=None)
    p.add_argument("--plan_camera_label_fontsize", type=int, default=None)
    p.add_argument("--board_near_camera_fontsize", type=int, default=None)
    p.add_argument(
        "--layout_title",
        type=str,
        default=None,
        help="Title used when --render_layout is enabled.",
    )
    p.add_argument("--render_layout", action="store_true", help="Render camera_layout_plan.[pdf|png] if matplotlib is available.")
    return p.parse_args()


def write_manifests(
    output_dir: Path,
    cameras: Sequence[CameraRec],
    boards: Sequence[BoardRec],
    dvrs: Dict[str, dict],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cam_csv = output_dir / "cameras_manifest.csv"
    board_csv = output_dir / "boards_manifest.csv"
    dvr_csv = output_dir / "dvr_assignments.csv"

    with cam_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["camera_id", "row_index", "col_index", "x_center_ft", "y_center_ft", "x_min_ft", "x_max_ft", "y_min_ft", "y_max_ft"])
        for c in cameras:
            w.writerow([c.camera_id, c.row_index, c.col_index, f"{c.x_center_ft:.3f}", f"{c.y_center_ft:.3f}", f"{c.x_min_ft:.3f}", f"{c.x_max_ft:.3f}", f"{c.y_min_ft:.3f}", f"{c.y_max_ft:.3f}"])

    with board_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["board_id", "x_left_ft", "y_bottom_ft", "install_row", "row_index", "col_index", "tag_ids"])
        for b in boards:
            w.writerow([b.board_id, f"{b.x_left_ft:.3f}", f"{b.y_bottom_ft:.3f}", b.row_index + 1, b.row_index, b.col_index, ";".join(str(t) for t in b.tag_ids)])

    with dvr_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dvr_id", "side", "color", "camera_count", "camera_ids"])
        for dvr_id in sorted(dvrs.keys(), key=lambda s: int(s[3:])):
            info = dvrs[dvr_id]
            w.writerow([dvr_id, info["side"], info["color"], len(info["camera_ids"]), ";".join(info["camera_ids"])])


def maybe_render_layout(
    output_dir: Path,
    cameras: Sequence[CameraRec],
    boards: Sequence[BoardRec],
    dvrs: Dict[str, dict],
    field_width_ft: float,
    field_height_ft: float,
    layout_title: str,
) -> str:
    try:
        import update_layout as ul
    except Exception as exc:  # pragma: no cover
        return f"Skipped rendering: could not import update_layout ({exc})."

    ul_cams = [
        ul.Camera(
            camera_id=c.camera_id,
            row_index=c.row_index,
            col_index=c.col_index,
            x_center_ft=c.x_center_ft,
            y_center_ft=c.y_center_ft,
            x_min_ft=c.x_min_ft,
            x_max_ft=c.x_max_ft,
            y_min_ft=c.y_min_ft,
            y_max_ft=c.y_max_ft,
        )
        for c in cameras
    ]
    ul_boards = [
        ul.Board(
            board_id=b.board_id,
            row_index=b.row_index,
            col_index=b.col_index,
            x_left_ft=b.x_left_ft,
            y_bottom_ft=b.y_bottom_ft,
            tag_ids=b.tag_ids,
        )
        for b in boards
    ]
    ul.render_layout(
        cameras=ul_cams,
        boards=ul_boards,
        output_dir=output_dir,
        field_width=field_width_ft,
        field_height=field_height_ft,
        dvr_assignments=dvrs,
        layout_title=layout_title,
    )
    return "Rendered layout files."


def main() -> int:
    args = _parse_args()
    printed = load_printed_boards(args.printed_boards_csv)

    if (args.num_cam_cols is None) ^ (args.num_cam_rows is None):
        raise ValueError("Provide both --num_cam_cols and --num_cam_rows, or omit both for auto mode.")

    forced_mode = args.num_cam_cols is not None and args.num_cam_rows is not None
    if forced_mode:
        x_axis = compute_axis_fixed_count(
            field_span_ft=args.field_width_ft,
            cam_span_ft=args.cam_width_ft,
            overlap_ratio=args.overlap_x_ratio,
            min_edge_coverage_ratio=args.min_edge_coverage_ratio,
            min_edge_margin_ft=args.min_edge_margin_ft,
            target_overlap_ft=args.target_overlap_x_ft,
            coord_step_ft=args.coord_step_ft,
            count=args.num_cam_cols,
            axis_label="X",
        )
        y_axis = compute_axis_fixed_count(
            field_span_ft=args.field_height_ft,
            cam_span_ft=args.cam_height_ft,
            overlap_ratio=args.overlap_y_ratio,
            min_edge_coverage_ratio=args.min_edge_coverage_ratio,
            min_edge_margin_ft=args.min_edge_margin_ft,
            target_overlap_ft=args.target_overlap_y_ft,
            coord_step_ft=args.coord_step_ft,
            count=args.num_cam_rows,
            axis_label="Y",
        )
    else:
        x_axis = compute_axis_auto_count(
            field_span_ft=args.field_width_ft,
            cam_span_ft=args.cam_width_ft,
            overlap_ratio=args.overlap_x_ratio,
            min_edge_coverage_ratio=args.min_edge_coverage_ratio,
            min_edge_margin_ft=args.min_edge_margin_ft,
            target_overlap_ft=args.target_overlap_x_ft,
            coord_step_ft=args.coord_step_ft,
            axis_label="X",
        )
        y_axis = compute_axis_auto_count(
            field_span_ft=args.field_height_ft,
            cam_span_ft=args.cam_height_ft,
            overlap_ratio=args.overlap_y_ratio,
            min_edge_coverage_ratio=args.min_edge_coverage_ratio,
            min_edge_margin_ft=args.min_edge_margin_ft,
            target_overlap_ft=args.target_overlap_y_ft,
            coord_step_ft=args.coord_step_ft,
            axis_label="Y",
        )

    cameras = build_cameras(
        field_width_ft=args.field_width_ft,
        field_height_ft=args.field_height_ft,
        cam_width_ft=args.cam_width_ft,
        cam_height_ft=args.cam_height_ft,
        x_centers=x_axis.centers,
        y_centers=y_axis.centers,
        numbering_order=args.numbering_order,
    )
    boards, slot_count = build_reused_boards(
        printed_boards=printed,
        x_centers=x_axis.centers,
        y_centers=y_axis.centers,
        board_width_ft=args.board_width_ft,
        board_height_ft=args.board_height_ft,
        coord_step_ft=args.coord_step_ft,
        board_offset_x_ft=args.board_offset_x_ft,
        board_offset_y_ft=args.board_offset_y_ft,
        field_width_ft=args.field_width_ft,
        field_height_ft=args.field_height_ft,
        placement_order=args.numbering_order,
    )
    dvrs = assign_cameras_to_dvrs(
        cameras=cameras,
        num_dvrs=args.num_dvrs,
        field_height_ft=args.field_height_ft,
        max_cams_per_dvr=args.max_cams_per_dvr,
    )

    out = args.output_dir
    write_manifests(out, cameras, boards, dvrs)

    summary_lines = [
        "Reuse Layout Summary",
        f"Field: {args.field_width_ft:.1f} ft x {args.field_height_ft:.1f} ft",
        f"Camera grid: {len(x_axis.centers)} x {len(y_axis.centers)} = {len(cameras)} cameras",
        f"Camera grid mode: {'forced' if forced_mode else 'auto-suggested'}",
        f"X overlap achieved: {x_axis.overlap_ft:.2f} ft (target >= {args.target_overlap_x_ft:.2f})",
        f"Y overlap achieved: {y_axis.overlap_ft:.2f} ft (target >= {args.target_overlap_y_ft:.2f})",
        f"X edge margins: L={x_axis.left_margin_ft:.2f} ft, R={x_axis.right_margin_ft:.2f} ft",
        f"Y edge margins: B={y_axis.left_margin_ft:.2f} ft, T={y_axis.right_margin_ft:.2f} ft",
        f"Board slots in new layout: {slot_count}",
        f"Printed boards available: {len(printed)}",
        f"Boards reused now: {len(boards)}",
        "Reused board IDs: " + ", ".join(b.board_id for b in boards),
        f"DVRs: {args.num_dvrs} (max cams per DVR: {args.max_cams_per_dvr})",
        f"Numbering/placement order: {args.numbering_order}",
        f"Output directory: {out}",
    ]
    summary_path = out / "reuse_summary.txt"
    out.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    render_status = "Rendering not requested."
    if args.render_layout:
        layout_title = args.layout_title
        if not layout_title:
            layout_title = (
                f"Layout Plan | Field {args.field_width_ft}x{args.field_height_ft} ft | "
                f"Camera Coverage {args.cam_width_ft}x{args.cam_height_ft} ft"
            )
        render_status = maybe_render_layout(
            output_dir=out,
            cameras=cameras,
            boards=boards,
            dvrs=dvrs,
            field_width_ft=args.field_width_ft,
            field_height_ft=args.field_height_ft,
            layout_title=layout_title,
        )
        summary_path.write_text("\n".join(summary_lines + [render_status]) + "\n", encoding="utf-8")

    print("\n".join(summary_lines))
    print(render_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
