#!/usr/bin/env python3
"""Annotate farm camera stills and report AprilTag overlap between views."""

from __future__ import annotations

import csv
import json
import re
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "Post-Processing" / "Cams"
OUTPUT = ROOT / "AprilTag" / "_Outputs" / "farm_camera_review"
TAG_SIZE_M = 8 * 0.0254
CAMERA_MATRIX = np.array([[1500.0, 0.0, 960.0], [0.0, 1500.0, 540.0], [0.0, 0.0, 1.0]])
DISTORTION = np.array([-0.365, 0.085, 0.0, 0.0, 0.0])
OBJECT_CORNERS = np.array(
    [[-TAG_SIZE_M / 2, TAG_SIZE_M / 2, 0],
     [TAG_SIZE_M / 2, TAG_SIZE_M / 2, 0],
     [TAG_SIZE_M / 2, -TAG_SIZE_M / 2, 0],
     [-TAG_SIZE_M / 2, -TAG_SIZE_M / 2, 0]], dtype=np.float32
)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def detect(image: np.ndarray, detector: cv2.aruco.ArucoDetector) -> list[dict]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found: dict[int, dict] = {}
    # A second illumination pass helps with glare and low contrast.
    for variant in (gray, cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)):
        corners, ids, _ = detector.detectMarkers(variant)
        if ids is None:
            continue
        for quad, tag_id in zip(corners, ids.flatten()):
            pts = quad.reshape(4, 2).astype(np.float32)
            area = abs(cv2.contourArea(pts))
            if area < 100:
                continue
            tag_id = int(tag_id)
            if tag_id in found and found[tag_id]["area_px2"] >= area:
                continue
            ok, rvec, tvec = cv2.solvePnP(
                OBJECT_CORNERS, pts, CAMERA_MATRIX, DISTORTION,
                flags=cv2.SOLVEPNP_IPPE_SQUARE,
            )
            distance = float(np.linalg.norm(tvec)) if ok and tvec[2, 0] > 0 else None
            projected, _ = cv2.projectPoints(OBJECT_CORNERS, rvec, tvec, CAMERA_MATRIX, DISTORTION) if ok else (None, None)
            reprojection = float(np.mean(np.linalg.norm(projected.reshape(4, 2) - pts, axis=1))) if ok else None
            found[tag_id] = {
                "tag_id": tag_id,
                "center_px": [round(float(v), 1) for v in pts.mean(axis=0)],
                "corners_px": [[round(float(v), 1) for v in p] for p in pts],
                "area_px2": round(area, 1),
                "approx_distance_m": round(distance, 3) if distance is not None else None,
                "approx_camera_xyz_m": [round(float(v), 3) for v in tvec.flatten()] if distance is not None else None,
                "reprojection_error_px": round(reprojection, 2) if reprojection is not None else None,
            }
    return [found[key] for key in sorted(found)]


def annotate(image: np.ndarray, camera: str, tags: list[dict]) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(output, (0, 0), (430, 62), (25, 25, 25), -1)
    cv2.putText(output, f"{camera}: {len(tags)} detected tags", (12, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    for tag in tags:
        pts = np.array(tag["corners_px"], dtype=np.int32)
        cv2.polylines(output, [pts], True, (0, 230, 75), 3, cv2.LINE_AA)
        x, y = map(int, tag["center_px"])
        label = f"ID {tag['tag_id']}"
        if tag["approx_distance_m"] is not None:
            label += f"  ~{tag['approx_distance_m']:.2f} m"
        (width, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        x = min(max(0, x - width // 2), output.shape[1] - width - 10)
        y = min(max(24, y - 12), output.shape[0] - 5)
        cv2.rectangle(output, (x - 4, y - 19), (x + width + 5, y + 5), (20, 20, 20), -1)
        cv2.putText(output, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 2, cv2.LINE_AA)
    return output


def main() -> None:
    images = sorted(INPUT.glob("*.jpg"))
    if not images:
        raise SystemExit(f"No JPEG images found in {INPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    overlays = OUTPUT / "overlays"
    overlays.mkdir(exist_ok=True)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    all_tags: dict[str, list[dict]] = {}
    image_names: dict[str, str] = {}
    detection_rows = []
    for path in images:
        match = re.search(r"_C(\d\d)_", path.name)
        if not match:
            raise ValueError(f"Camera ID missing from {path.name}")
        camera = f"C{match.group(1)}"
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Cannot read {path}")
        if image.shape[:2] != (1080, 1920):
            raise ValueError(f"Unexpected dimensions for {path}: {image.shape[:2]}")
        tags = detect(image, detector)
        all_tags[camera] = tags
        image_names[camera] = path.name
        overlay_name = f"{camera}_annotated.jpg"
        cv2.imwrite(str(overlays / overlay_name), annotate(image, camera, tags),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        for tag in tags:
            detection_rows.append({
                "camera": camera, "image": path.name, "tag_family": "tag36h11",
                "tag_id": tag["tag_id"], "center_x_px": tag["center_px"][0],
                "center_y_px": tag["center_px"][1],
                "corners_px_json": json.dumps(tag["corners_px"]),
                "area_px2": tag["area_px2"],
                "approx_distance_m": tag["approx_distance_m"],
                "approx_camera_xyz_m_json": json.dumps(tag["approx_camera_xyz_m"]),
                "reprojection_error_px": tag["reprojection_error_px"],
                "overlay": f"overlays/{overlay_name}",
            })
        print(f"{camera}: {len(tags)} tags: {','.join(str(t['tag_id']) for t in tags)}")
    cameras = sorted(all_tags)
    summary = [{"camera": c, "image": image_names[c], "tag_count": len(all_tags[c]),
                "tag_ids": ";".join(str(t["tag_id"]) for t in all_tags[c]),
                "overlay": f"overlays/{c}_annotated.jpg"} for c in cameras]
    overlaps = []
    for a, b in combinations(cameras, 2):
        a_ids = {t["tag_id"] for t in all_tags[a]}
        b_ids = {t["tag_id"] for t in all_tags[b]}
        common = sorted(a_ids & b_ids)
        if not common and abs(int(a[1:]) - int(b[1:])) != 1:
            continue
        overlaps.append({"camera_a": a, "camera_b": b,
                         "consecutive_camera_numbers": abs(int(a[1:]) - int(b[1:])) == 1,
                         "shared_tag_count": len(common),
                         "shared_tag_ids": ";".join(map(str, common)),
                         "relationship": "observed_shared_view" if common else "no_shared_tag_detected"})
    overlaps.sort(key=lambda row: (-row["shared_tag_count"], row["camera_a"], row["camera_b"]))
    write_csv(OUTPUT / "detections.csv", detection_rows, list(detection_rows[0]) if detection_rows else
              ["camera", "image", "tag_family", "tag_id", "center_x_px", "center_y_px",
               "corners_px_json", "area_px2", "approx_distance_m", "approx_camera_xyz_m_json",
               "reprojection_error_px", "overlay"])
    write_csv(OUTPUT / "camera_summary.csv", summary, list(summary[0]))
    write_csv(OUTPUT / "camera_overlap.csv", overlaps,
              ["camera_a", "camera_b", "consecutive_camera_numbers", "shared_tag_count",
               "shared_tag_ids", "relationship"])
    (OUTPUT / "detections.json").write_text(json.dumps({
        "tag_family": "tag36h11", "tag_size_m": TAG_SIZE_M,
        "calibration_status": "approximate_shared_profile",
        "camera_matrix": CAMERA_MATRIX.tolist(), "distortion_coefficients": DISTORTION.tolist(),
        "coordinate_note": "camera xyz: x right, y down, z forward; tag is ground mounted",
        "images": {c: {"source": image_names[c], "tags": all_tags[c]} for c in cameras},
    }, indent=2) + "\n")
    (OUTPUT / "README.md").write_text(
        "# Farm camera AprilTag review\n\n"
        "20 camera stills were processed with OpenCV's tag36h11 detector. "
        "The tag's black outer square is assumed to measure 8 inches (0.2032 m).\n\n"
        "- `overlays/`: visible outlines, IDs, and approximate camera-to-tag distances.\n"
        "- `detections.csv`: one row per decoded tag, with image coordinates and approximate pose.\n"
        "- `camera_summary.csv`: tag IDs visible in each camera.\n"
        "- `camera_overlap.csv`: pairs with shared decoded IDs, plus consecutive-number pairs "
        "with no shared detection. Shared IDs establish observed view overlap; numbered "
        "neighbors alone do not prove physical adjacency.\n"
        "- `detections.json`: full precision source metadata and per-camera records.\n\n"
        "Distances and camera XYZ are approximate because the intrinsics and distortion "
        "were averaged from four similar cameras, not calibrated per installed camera. "
        "These are camera-relative poses, not surveyed farm coordinates. "
        "A missing tag may be obscured or unreadable in this still.\n"
    )
    print(f"Wrote {len(detection_rows)} detections and {len(overlaps)} overlap rows to {OUTPUT}")


if __name__ == "__main__":
    main()
