# Tabloid checkerboard for robot camera calibration

Print **checkerboard_11x6_inner_30mm_tabloid_17x11.pdf**. This is a one-page vector PDF, not a screenshot. The SVG is an editable source alternative; prefer the PDF for printing. The generator and JSON geometry specification are included for reproducibility.

## Exact target geometry

| Setting | Value |
| --- | --- |
| Paper | US Tabloid / ANSI B, 17 × 11 inches, landscape |
| Inner corners | 11 columns × 6 rows = 66 |
| Actual squares | 12 columns × 7 rows |
| Nominal square side | 30.00 mm |
| Pattern rectangle | 360 × 210 mm |
| Clear white border | 35.9 mm left/right; 34.7 mm top/bottom |
| Colour | Solid black and white, no labels or marks near the pattern |

## Print and measure

1. Choose **Tabloid / 11 × 17**, **landscape**, **Actual size / 100%**, one page per sheet, single-sided. Turn off Fit to page, Shrink oversized pages, booklet/poster tiling and borderless enlargement. Do not print a screenshot or resize this to Letter paper.
2. Use a sharp, high-quality print on matte white paper. Avoid glossy lamination, ink bleed and creases. The PDF requests no print scaling, but you must still verify your printer's settings.
3. Optionally print **print_scale_check_tabloid.pdf** using identical settings. Its horizontal and vertical endpoint-to-endpoint distances are 100 mm; the box is 30 × 30 mm. That separate sheet is a printer check, not the calibration target.
4. Measure the checkerboard itself, after mounting: five adjacent square widths should span **150 mm**, and five square heights should span **150 mm**. Measure several runs across different parts of the board. The complete square pattern should span **360 × 210 mm**.
5. Mount the entire sheet smoothly onto a rigid, flat backing. Keep its white margins. Paper sag, warped backing and uneven glue can introduce errors even if the calibration's reprojection error looks good.
6. Enter the **actual measured square spacing** in the app. If printing is uniformly scaled, use that measured value. If horizontal and vertical spacings differ, or spacing varies across the print, correct/reprint the target: the current app assumes uniform square dimensions in both directions.

Flat mounting, checking printer scaling and retaining a white border are recommended in the [Kalibr target instructions](https://github.com/ethz-asl/kalibr/wiki/calibration-targets).

## Use with original lenses or a 6 mm lens

Use this same printed pattern for either lens. It is a practical tabloid-sized target, not a guarantee of measurement accuracy over 1–24 feet.

- Create a **new profile for each physical camera + lens + locked focus + resolution**. Suggested labels: `ELP / original`, `ELP / M12 6 mm`, `B0592 / original`, etc. Recalibrate after changing lenses or focus.
- In the calibration website, select **11 × 6 inner corners** and set **Measured square size (mm)** to the measured value, nominally **30.00**. The board dropdown may still say “large matte checkerboard”; its 11 × 6 corner layout also matches this print.
- **Do not extend an old 76.2 mm-square session with this 30 mm target.** Start a new profile so old and new corner geometry are not mixed.
- Set and lock the lens focus for the intended robot task first. Move the board to distances where it is sharp, fully visible and occupies a substantial part of the image. Do not refocus just to see a close calibration board and then change focus back afterward.
- A 6 mm lens usually gives a narrower view than a shorter-focal-length lens on the same sensor. Its actual field of view depends on the sensor and imaging mode. Move the board farther away if it does not fit; no fixed capture distance can be specified from “6 mm” alone.
- Choose the distortion model to match the lens; 6 mm by itself does not imply a fisheye model.
- Collect about **40–60 useful poses** if needed to improve your earlier coverage. Include all image edges and corners, several apparent board sizes, and varied tilts in both directions. Keep the full inner-corner grid visible and pause for a sharp capture. A high image count is not a substitute for varied coverage.
- Use the app's TL/TR/BL/BR corner-view counters to identify missing regions. Each camera can accept different frames. If a useful view cannot fit all three cameras at once, collect it for one camera at a time.

Target size should be matched to field of view and focus, and calibration images should cover the full image area; see [Calib.io's calibration guidance](https://calib.io/blogs/knowledge-base/calibration-best-practices) and [target-size guidance](https://calib.io/pages/faqs).

## Validate the 1–24-foot robot task separately

You do **not** need to photograph this small board at every distance up to 24 feet. If it becomes tiny or blurry at a distance, that view is poor calibration evidence. Use the larger rigid board in a separate profile/session when a distant calibration target is needed; do not mix its square size into this session.

After calibrating, test your actual AprilTags at independently measured **1, 3, 6, 12 and 24 feet**, including angled/edge views and expected lighting. Use the actual tag detection-edge size (excluding the surrounding white margin). Keep camera/lens/focus/resolution matched to the calibration.

Check that the complete tag fits and remains focused at 1 foot, particularly with a 6 mm lens. At 24 feet, sufficient tag pixels, sharpness, lighting and motion blur still limit accuracy. The lens that improves far-range detail may reduce close-range coverage.

Record signed distance error, jitter and detection success. Use a consistent distance definition (forward depth versus straight-line range). A low checkerboard reprojection error alone does not demonstrate accurate AprilTag measurements throughout the robot's operating range.

## File verification

The generated target PDF has a 1224 × 792-point page (17 × 11 inches), exact vector square geometry and print scaling set to None. Its rendered page was checked with OpenCV: all 66 inner corners were detected and horizontal/vertical square spacing matched the nominal 30 mm geometry. This verifies the file, not a physical printer's output.

From this calibration directory, regenerate the PDFs, SVG and JSON with:

```sh
python3 generate_checkerboard.py
```
