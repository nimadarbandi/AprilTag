# AprilTag Video Reader

A Flask website that accepts a video upload, detects AprilTags frame by frame, draws tag bounding polygons and metadata directly on the output video, and provides a timestamped JSON report.

## Run

```bash
cd APrilTag_Reader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`, upload a video, select its AprilTag family and physical tag side length in inches. The result page has the browser-playable annotation video and a panel which updates with the video timeline. It also exposes the full JSON report for download.

If port 5000 is already in use, launch on another port, for example `python app.py --port 5001`, then open `http://127.0.0.1:5001`.

`ffmpeg` is used to make the output H.264 MP4 browser-compatible. Install it with `brew install ffmpeg` on macOS if it is not already available.

## Distance accuracy

Distance comes from AprilTag pose estimation. Enter the calibrated camera focal lengths (`fx`, `fy`, in pixels) for measurements that can be considered calibrated. The camera principal point is assumed to be the frame centre and no lens distortion is modeled, so for the best result replace that with a full camera calibration in `app.py`. When focal lengths are omitted, the displayed distance is intentionally labelled **estimated**; it must not be used for precision measurement.

The JSON contains the tag ID, frame and timestamp, center/corner pixels, camera-to-tag distance in metres and feet, translation vector, detection confidence (when the Pupil backend is used), and whether the range was calibrated.
