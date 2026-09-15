#!/usr/bin/env python3
"""Upload a video, detect AprilTags, and return a playable annotated video."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import uuid
import argparse
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

try:
    from pupil_apriltags import Detector as PupilDetector
except ImportError:  # OpenCV fallback is selected at runtime.
    PupilDetector = None


ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
METERS_TO_FEET = 3.28084
INCHES_TO_METERS = 0.0254

app = Flask(__name__)
app.config.update(
    SECRET_KEY="change-this-before-exposing-the-app",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024 * 1024,  # 2 GB
)


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


class TagDetector:
    """Small adapter over pupil_apriltags and OpenCV's AprilTag backend."""

    def __init__(self, family: str):
        self.family = family
        self.backend = "pupil_apriltags" if PupilDetector else "opencv"
        if PupilDetector:
            self.detector = PupilDetector(
                families=family, nthreads=2, quad_decimate=1.0,
                quad_sigma=0.0, refine_edges=1, decode_sharpening=0.25,
            )
            return

        if not hasattr(cv2, "aruco"):
            raise RuntimeError(
                "No AprilTag detector is installed. Install pupil-apriltags or opencv-contrib-python."
            )
        dictionaries = {
            "tag16h5": cv2.aruco.DICT_APRILTAG_16h5,
            "tag25h9": cv2.aruco.DICT_APRILTAG_25h9,
            "tag36h10": cv2.aruco.DICT_APRILTAG_36h10,
            "tag36h11": cv2.aruco.DICT_APRILTAG_36h11,
        }
        if family not in dictionaries:
            raise ValueError(f"Unsupported tag family: {family}")
        dictionary = cv2.aruco.getPredefinedDictionary(dictionaries[family])
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    def detect(self, gray: np.ndarray, camera_params, tag_size_m: float):
        if self.backend == "pupil_apriltags":
            return self.detector.detect(
                gray, estimate_tag_pose=True, camera_params=camera_params, tag_size=tag_size_m
            )

        corners, ids, _ = self.detector.detectMarkers(gray)
        results = []
        if ids is None:
            return results
        for pts, tag_id in zip(corners, ids.flatten()):
            pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
            # solvePnP makes the same pose information available as pupil_apriltags.
            half = tag_size_m / 2
            object_points = np.array(
                [[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], np.float32
            )
            fx, fy, cx, cy = camera_params
            matrix = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
            ok, rvec, tvec = cv2.solvePnP(object_points, pts, matrix, np.zeros(5), flags=cv2.SOLVEPNP_IPPE_SQUARE)
            results.append(OpenCVDetection(int(tag_id), pts, tvec if ok else None))
        return results


class OpenCVDetection:
    def __init__(self, tag_id: int, corners: np.ndarray, pose_t):
        self.tag_id = tag_id
        self.corners = corners
        self.center = corners.mean(axis=0)
        self.pose_t = pose_t
        self.decision_margin = None
        self.hamming = None


def make_record(detection, frame_number: int, timestamp_s: float, calibrated: bool) -> dict:
    corners = np.asarray(detection.corners, dtype=float)
    pose_t = getattr(detection, "pose_t", None)
    translation = None
    distance_m = None
    if pose_t is not None:
        translation = [round(float(value), 5) for value in np.asarray(pose_t).reshape(-1)[:3]]
        distance_m = float(np.linalg.norm(np.asarray(pose_t).reshape(-1)[:3]))
    return {
        "frame": frame_number,
        "timestamp_s": round(timestamp_s, 3),
        "tag_id": int(detection.tag_id),
        "center_px": [round(float(value), 1) for value in detection.center],
        "corners_px": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
        "distance_m": round(distance_m, 3) if distance_m is not None else None,
        "distance_ft": round(distance_m * METERS_TO_FEET, 2) if distance_m is not None else None,
        "distance_quality": "calibrated" if calibrated else "estimated from supplied focal length",
        "translation_m": translation,
        "decision_margin": round(float(detection.decision_margin), 2)
        if getattr(detection, "decision_margin", None) is not None else None,
        "hamming": getattr(detection, "hamming", None),
    }


def label(frame: np.ndarray, lines: list[str], anchor: tuple[int, int]) -> None:
    """Draw a readable multi-line information panel beside a bounding box."""
    font, scale, thickness = cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1
    widths = [cv2.getTextSize(line, font, scale, thickness)[0][0] for line in lines]
    height = 8 + len(lines) * 20
    x = min(max(4, anchor[0]), max(4, frame.shape[1] - max(widths) - 18))
    y = min(max(4, anchor[1]), max(4, frame.shape[0] - height - 4))
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + max(widths) + 14, y + height), (25, 25, 25), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (x + 7, y + 18 + index * 20), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def annotate(frame: np.ndarray, records: list[dict]) -> np.ndarray:
    for record in records:
        corners = np.asarray(record["corners_px"], dtype=np.int32)
        cv2.polylines(frame, [corners.reshape(-1, 1, 2)], True, (52, 220, 88), 3, cv2.LINE_AA)
        for index, point in enumerate(corners):
            cv2.circle(frame, tuple(point), 4, (30, 30, 240) if index == 0 else (52, 220, 88), -1)
        rightmost = corners[np.argmax(corners[:, 0])]
        dist = "distance unavailable" if record["distance_m"] is None else f"distance: {record['distance_m']:.3f} m / {record['distance_ft']:.2f} ft"
        quality = "pose: calibrated" if record["distance_quality"] == "calibrated" else "pose: estimated"
        label(frame, [f"AprilTag {record['tag_id']}", dist, quality], (int(rightmost[0]) + 10, int(rightmost[1]) - 10))
    return frame


def process_video(source: Path, destination: Path, tag_size_m: float, family: str, fx: float | None, fy: float | None) -> dict:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open this video. Try MP4 (H.264) or MOV.")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if width <= 0 or height <= 0:
        raise RuntimeError("The video does not contain readable frames.")
    # In the absence of calibration, an image-width focal estimate is useful for rough range only.
    calibrated = fx is not None and fy is not None
    fx, fy = fx or float(width), fy or float(width)
    camera_params = (fx, fy, width / 2, height / 2)
    detector = TagDetector(family)
    intermediate = destination.with_suffix(".avi")
    writer = cv2.VideoWriter(str(intermediate), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Unable to create the annotated video file.")

    detections, tag_ids, frame_number = [], set(), 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found = detector.detect(gray, camera_params, tag_size_m)
            records = [make_record(item, frame_number, frame_number / fps, calibrated) for item in found]
            detections.extend(records)
            tag_ids.update(item["tag_id"] for item in records)
            writer.write(annotate(frame, records))
            frame_number += 1
    finally:
        cap.release()
        writer.release()

    # MJPEG AVI is reliable for OpenCV writing; ffmpeg makes a universally playable H.264 MP4.
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        completed = subprocess.run(
            [ffmpeg, "-y", "-i", str(intermediate), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination)],
            capture_output=True, text=True,
        )
        intermediate.unlink(missing_ok=True)
        if completed.returncode:
            raise RuntimeError("ffmpeg could not encode the browser video: " + completed.stderr[-500:])
    else:
        intermediate.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg is required to create a browser-playable MP4. Install ffmpeg and try again.")

    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "source_name": source.name,
        "video": {"width": width, "height": height, "fps": round(fps, 3), "frame_count": frame_count},
        "detector": {"family": family, "backend": detector.backend, "tag_size_m": tag_size_m,
                     "camera_calibrated": calibrated, "camera_params": {"fx": fx, "fy": fy, "cx": width / 2, "cy": height / 2}},
        "summary": {"unique_tag_ids": sorted(tag_ids), "detection_count": len(detections), "frames_processed": frame_number},
        "detections": detections,
    }


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        upload = request.files.get("video")
        if not upload or not upload.filename:
            flash("Choose a video file first.", "error")
            return redirect(url_for("index"))
        if not allowed_file(upload.filename):
            flash("Unsupported file type. Upload MP4, MOV, AVI, MKV, WebM, or M4V.", "error")
            return redirect(url_for("index"))
        try:
            tag_size_inches = float(request.form["tag_size_inches"])
            if tag_size_inches <= 0:
                raise ValueError
            tag_size_m = tag_size_inches * INCHES_TO_METERS
            focal_x = request.form.get("fx", "").strip()
            focal_y = request.form.get("fy", "").strip()
            fx = float(focal_x) if focal_x else None
            fy = float(focal_y) if focal_y else None
            if (fx is None) != (fy is None) or (fx is not None and (fx <= 0 or fy <= 0)):
                raise ValueError
        except ValueError:
            flash("Tag size (inches) and focal lengths must be positive numbers; provide both focal lengths or neither.", "error")
            return redirect(url_for("index"))

        job_id = uuid.uuid4().hex
        job_dir = OUTPUTS / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        source = UPLOADS / f"{job_id}_{secure_filename(upload.filename)}"
        upload.save(source)
        try:
            result = process_video(source, job_dir / "annotated.mp4", tag_size_m, request.form.get("family", "tag36h11"), fx, fy)
            (job_dir / "detections.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        except Exception as error:
            shutil.rmtree(job_dir, ignore_errors=True)
            flash(f"Processing failed: {error}", "error")
            return redirect(url_for("index"))
        finally:
            source.unlink(missing_ok=True)
        return redirect(url_for("result", job_id=job_id))
    return render_template("index.html")


@app.route("/result/<job_id>")
def result(job_id: str):
    metadata_path = OUTPUTS / job_id / "detections.json"
    if not metadata_path.is_file():
        abort(404)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return render_template("result.html", job_id=job_id, metadata=metadata)


@app.route("/output/<job_id>/<path:filename>")
def output(job_id: str, filename: str):
    directory = OUTPUTS / job_id
    if not directory.is_dir():
        abort(404)
    return send_from_directory(directory, filename, as_attachment=filename.endswith(".json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AprilTag Video Reader web server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--no-debug", action="store_true", help="Disable Flask debug mode")
    args = parser.parse_args()
    UPLOADS.mkdir(exist_ok=True)
    OUTPUTS.mkdir(exist_ok=True)
    app.run(host=args.host, port=args.port, debug=not args.no_debug)
