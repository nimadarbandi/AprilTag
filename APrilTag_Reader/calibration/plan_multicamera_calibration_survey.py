#!/usr/bin/env python3
"""Draw a four-camera calibration survey and write its rover/tag-board CSV files.

Coordinate convention: X is the 24 ft building length (left to right in the plot),
Y is the 11 ft building width (bottom to top). All output coordinates are in feet.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from xml.sax.saxutils import escape


# ── Site geometry — edit only these values if the surveyed layout changes. ────
AREA_LENGTH_FT = 24.0
AREA_WIDTH_FT = 11.0
CAMERA_FOV_LENGTH_FT = 14.0  # assumed usable floor coverage in X
CAMERA_FOV_WIDTH_FT = 7.0    # assumed usable floor coverage in Y

# Normalized camera grid: C1=(0,0), C2=(1,0), C3=(0,1), C4=(1,1).
# This gives 12 ft separation along X and 6 ft separation along Y.
CAMERAS = {"C1": (6.0, 2.5), "C2": (18.0, 2.5), "C3": (6.0, 8.5), "C4": (18.0, 8.5)}

# Wall navigation boards are vertical, with their printed face pointing into the
# room. Set this to the measured height of the rover front-camera lens center.
ROBOT_CAMERA_HEIGHT_IN = 18.0  # REQUIRED: measure and replace before installation

# Four IDs per physical board, in generator order: top-left, top-right,
# bottom-left, bottom-right. Change START_TAG_ID to avoid ID collisions.
START_TAG_ID = 0
BOARD_CENTERS = {
    # x_ft, y_ft, wall, yaw, pitch, roll. The Euler angles use the calibration
    # website's Rz(yaw) @ Ry(pitch) @ Rx(roll) convention.
    "W1": (0.0, 1.5, "west", 90.0, 0.0, 90.0),
    "W2": (0.0, 5.5, "west", 90.0, 0.0, 90.0),
    "W3": (0.0, 9.5, "west", 90.0, 0.0, 90.0),
    "E1": (24.0, 1.5, "east", -90.0, 0.0, 90.0),
    "E2": (24.0, 5.5, "east", -90.0, 0.0, 90.0),
    "E3": (24.0, 9.5, "east", -90.0, 0.0, 90.0),
    "S1": (4.0, 0.0, "south", 180.0, 0.0, 90.0),
    "S2": (12.0, 0.0, "south", 180.0, 0.0, 90.0),
    "S3": (20.0, 0.0, "south", 180.0, 0.0, 90.0),
    "N1": (4.0, 11.0, "north", 0.0, 0.0, 90.0),
    "N2": (12.0, 11.0, "north", 0.0, 0.0, 90.0),
    "N3": (20.0, 11.0, "north", 0.0, 0.0, 90.0),
}

# Intrinsic calibration: 25 physical positions per camera, with two rover
# headings at every position. This creates 50 candidates so quality filtering
# can retain 30–40 strong, non-duplicate images for each camera.
GRID_POINTS_PER_AXIS = 5
GRID_EDGE_INSET_RATIO = 0.10
# Each camera route uses boards on the two opposite walls. This keeps the
# vertical boards well within the front camera's view instead of looking at a
# nearby wall board at a severe grazing angle.
CAMERA_NAV_WALLS = {
    "C1": ("north", "east"),
    "C2": ("north", "west"),
    "C3": ("south", "east"),
    "C4": ("south", "west"),
}
DWELL_SECONDS = 2.0
CAMERA_ROUTE_ORDER = ("C1", "C2", "C4", "C3")
CAMERA_COLORS = {"C1": "#e58a20", "C2": "#7c55c7", "C3": "#159fb5", "C4": "#d44b4b"}
HANDOFF_STOPS = {
    "H01_four_camera_overlap": (12.0, 5.5), "H02_x_overlap_south": (12.0, 3.8),
    "H03_x_overlap_north": (12.0, 7.2), "H04_y_overlap_west": (6.0, 5.5),
    "H05_y_overlap_east": (18.0, 5.5),
}
OUTPUT_DIR = Path(__file__).resolve().parent / "survey_plan"


def evenly_spaced(start: float, end: float, count: int) -> tuple[float, ...]:
    return tuple(start + index * (end - start) / (count - 1) for index in range(count))


def camera_grid(camera_name: str) -> list[tuple[float, float]]:
    """Return a 5x5 inset snake grid within one camera's in-room coverage."""
    cx, cy = CAMERAS[camera_name]
    x_min = max(0.0, cx - CAMERA_FOV_LENGTH_FT / 2)
    x_max = min(AREA_LENGTH_FT, cx + CAMERA_FOV_LENGTH_FT / 2)
    y_min = max(0.0, cy - CAMERA_FOV_WIDTH_FT / 2)
    y_max = min(AREA_WIDTH_FT, cy + CAMERA_FOV_WIDTH_FT / 2)
    x_inset = (x_max - x_min) * GRID_EDGE_INSET_RATIO
    y_inset = (y_max - y_min) * GRID_EDGE_INSET_RATIO
    xs = evenly_spaced(x_min + x_inset, x_max - x_inset, GRID_POINTS_PER_AXIS)
    ys = evenly_spaced(y_min + y_inset, y_max - y_inset, GRID_POINTS_PER_AXIS)
    points: list[tuple[float, float]] = []
    for row, y in enumerate(ys):
        for x in (xs if row % 2 == 0 else tuple(reversed(xs))):
            points.append((round(x, 3), round(y, 3)))
    return points


def nearest_board_on_wall(x: float, y: float, wall: str) -> tuple[str, tuple[float, ...]]:
    candidates = [(board_id, values) for board_id, values in BOARD_CENTERS.items() if values[2] == wall]
    return min(candidates, key=lambda item: math.hypot(item[1][0] - x, item[1][1] - y))


def bearing_deg(x: float, y: float, target_x: float, target_y: float) -> float:
    """Return rover yaw where 0=+X/east and 90=+Y/north."""
    return round(math.degrees(math.atan2(target_y - y, target_x - x)) % 360.0, 1)


def primary_waypoints() -> list[dict[str, object]]:
    """Return four camera-specific calibration routes followed by handoff checks."""
    waypoints: list[dict[str, object]] = []
    sequence = 1
    for camera_name in CAMERA_ROUTE_ORDER:
        for position_index, (x, y) in enumerate(camera_grid(camera_name), start=1):
            for view_index, wall in enumerate(CAMERA_NAV_WALLS[camera_name], start=1):
                board_id, board = nearest_board_on_wall(x, y, wall)
                heading = bearing_deg(x, y, board[0], board[1])
                first_tag = START_TAG_ID + list(BOARD_CENTERS).index(board_id) * 4
                tag_ids = ";".join(str(first_tag + offset) for offset in range(4))
                waypoints.append({"sequence": sequence, "name": f"{camera_name}_P{position_index:02d}_V{view_index}_{board_id}",
                                  "kind": "checkerboard_capture", "target_camera": camera_name,
                                  "position_index": position_index, "x_ft": x, "y_ft": y,
                                  "heading_deg": heading, "dwell_s": DWELL_SECONDS,
                                  "navigation_board_id": board_id, "navigation_tag_ids": tag_ids,
                                  "save_rule": "save only if full, sharp, large-enough, and geometrically novel"})
                sequence += 1
    for name, (x, y) in HANDOFF_STOPS.items():
        waypoints.append({"sequence": sequence, "name": name, "kind": "handoff_validation",
                          "target_camera": "all visible", "position_index": "", "x_ft": x, "y_ft": y,
                          "heading_deg": 0, "dwell_s": 3.0, "save_rule": "compare global rover position across cameras"})
        waypoints[-1]["navigation_board_id"] = ""
        waypoints[-1]["navigation_tag_ids"] = ""
        sequence += 1
    return waypoints


def boards() -> list[dict[str, object]]:
    result = []
    for index, (board_id, values) in enumerate(BOARD_CENTERS.items()):
        x, y, wall, yaw, pitch, roll = values
        first = START_TAG_ID + index * 4
        result.append({"board_id": board_id, "wall": wall, "center_x_ft": x, "center_y_ft": y,
                       "center_z_in": ROBOT_CAMERA_HEIGHT_IN,
                       "yaw_deg": yaw, "pitch_deg": pitch, "roll_deg": roll,
                       "tag_ids_TL_TR_BL_BR": ";".join(str(first + offset) for offset in range(4)),
                       "mount_note": "vertical; printed face inward; printed top upward"})
    return result


def write_csvs(waypoints: list[dict[str, object]], board_rows: list[dict[str, object]]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for filename, rows in (("survey_waypoints.csv", waypoints), ("fixed_tag_boards.csv", board_rows)):
        with (OUTPUT_DIR / filename).open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def draw_plan(waypoints: list[dict[str, object]], board_rows: list[dict[str, object]]) -> Path:
    width, height, margin = 1600, 820, 100
    scale = min((width - 2 * margin) / AREA_LENGTH_FT, (height - 2 * margin) / AREA_WIDTH_FT)
    plot_w, plot_h = AREA_LENGTH_FT * scale, AREA_WIDTH_FT * scale
    x0, y0 = (width - plot_w) / 2, (height - plot_h) / 2
    def point(x: float, y: float) -> tuple[float, float]: return x0 + x * scale, y0 + plot_h - y * scale
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#172130}.small{font-size:12px}.label{font-size:14px;font-weight:bold}.title{font-size:26px;font-weight:bold}</style>',
             f'<text x="{width / 2}" y="38" text-anchor="middle" class="title">24 ft × 11 ft four-camera calibration survey</text>',
             f'<rect x="{x0}" y="{y0}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#172130" stroke-width="3"/>']
    for name, (x, y) in CAMERAS.items():
        left, top = point(x - CAMERA_FOV_LENGTH_FT / 2, y + CAMERA_FOV_WIDTH_FT / 2)
        lines.append(f'<rect x="{left}" y="{top}" width="{CAMERA_FOV_LENGTH_FT * scale}" height="{CAMERA_FOV_WIDTH_FT * scale}" fill="#78aefb" fill-opacity=".12" stroke="#316fc7" stroke-dasharray="7 5"/>')
        px, py = point(x, y)
        lines.extend([f'<circle cx="{px}" cy="{py}" r="14" fill="#164a91"/>', f'<text x="{px}" y="{py - 22}" text-anchor="middle" class="label">{name} ({x:g}, {y:g})</text>'])
    for row in board_rows:
        px, py = point(float(row["center_x_ft"]), float(row["center_y_ft"]))
        ids = escape(str(row["tag_ids_TL_TR_BL_BR"]).replace(";", ","))
        lines.extend([f'<rect x="{px - 9}" y="{py - 9}" width="18" height="18" fill="#b12275"/>', f'<text x="{px}" y="{py - 16}" text-anchor="middle" class="small" fill="#751547">{escape(str(row["board_id"]))}: {ids}</text>'])
    # Plot each physical position once. The CSV contains two heading actions
    # per dot, which is why it has 50 candidates per camera.
    for camera_name in CAMERA_ROUTE_ORDER:
        positions = [row for row in waypoints if row["kind"] == "checkerboard_capture"
                     and row["target_camera"] == camera_name and str(row["name"]).split("_V")[1].startswith("1_")]
        route = " ".join(f'{point(float(row["x_ft"]), float(row["y_ft"]))[0]:.1f},{point(float(row["x_ft"]), float(row["y_ft"]))[1]:.1f}' for row in positions)
        color = CAMERA_COLORS[camera_name]
        lines.append(f'<polyline points="{route}" fill="none" stroke="{color}" stroke-width="2.5" stroke-opacity=".68"/>')
        for row in positions:
            px, py = point(float(row["x_ft"]), float(row["y_ft"]))
            lines.append(f'<circle cx="{px}" cy="{py}" r="5" fill="{color}" stroke="white" stroke-width="1"/>')
    for row in waypoints:
        if row["kind"] == "handoff_validation":
            px, py = point(float(row["x_ft"]), float(row["y_ft"]))
            lines.extend([f'<path d="M {px} {py - 14} L {px + 4} {py - 4} L {px + 14} {py - 4} L {px + 6} {py + 3} L {px + 9} {py + 13} L {px} {py + 7} L {px - 9} {py + 13} L {px - 6} {py + 3} L {px - 14} {py - 4} L {px - 4} {py - 4} Z" fill="#138d54"/>', f'<text x="{px}" y="{py + 28}" text-anchor="middle" class="small" fill="#08703f">{escape(str(row["name"]))}</text>'])
    legend = " · ".join(f'{name} route = {CAMERA_COLORS[name]}' for name in CAMERA_ROUTE_ORDER)
    lines.extend([f'<text x="{x0}" y="{height - 66}" class="small">Each route: 25 positions × two named wall-board views = 50 candidates; retain the best 30–40 per camera.</text>',
                  f'<text x="{x0}" y="{height - 46}" class="small">Magenta = inward-facing 4-tag navigation boards at rover-camera height · Green = handoff tests.</text>',
                  f'<text x="{x0}" y="{height - 26}" class="small">Dashed blue rectangles are assumed 14 ft × 7 ft coverage. Route colors: {escape(legend)}</text>', '</svg>'])
    destination = OUTPUT_DIR / "camera_calibration_survey_plan.svg"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def main() -> None:
    waypoints, board_rows = primary_waypoints(), boards()
    write_csvs(waypoints, board_rows)
    print(f"Wrote {draw_plan(waypoints, board_rows)}")
    print(f"Wrote {OUTPUT_DIR / 'survey_waypoints.csv'}")
    print(f"Wrote {OUTPUT_DIR / 'fixed_tag_boards.csv'}")


if __name__ == "__main__":
    main()
