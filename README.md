# Camera Mesh and AprilTag Board Generator

Generate a camera coverage mesh for a rectangular field and produce printable AprilTag calibration boards at the camera-overlap intersections.

This repository contains a single Python CLI app:

- [`generate_camera_mesh_and_apriltag_boards.py`](generate_camera_mesh_and_apriltag_boards.py)

It is intended for calibration planning in large indoor spaces where you need to:

- estimate a camera grid from field dimensions and camera coverage
- place calibration boards in overlap regions between adjacent cameras
- export a field layout plan for installation
- generate per-board printable AprilTag PDFs and PNGs
- export CSV manifests for cameras, boards, and visibility relationships

## What It Generates

For each run, the script creates:

- `camera_layout_plan.pdf` and `camera_layout_plan.png`
- `cameras_manifest.csv`
- `boards_manifest.csv`
- `boards_manifest.pdf`
- `visibility_boards.csv`
- `visibility_cameras.csv`
- `boards_combined.pdf`
- one PDF and one PNG per board in `boards/`
- optional tiled poster PDFs in `boards_tiled/`

The included [`demo_output/`](demo_output) directory shows a complete example.

## How It Works

1. The script computes camera center positions along X and Y from the field size, camera footprint, overlap targets, and coordinate snap step.
2. It builds a rectangular camera grid.
3. It places one calibration board at each internal camera-grid intersection.
4. Each board gets four unique tag IDs in a fixed 2x2 layout.
5. The script exports both planning artifacts and print-ready board files.

Coordinate convention:

- origin is the bottom-left corner of the field
- `X` increases along field width
- `Y` increases along field height

## Requirements

- Python 3.10+
- `numpy`
- `matplotlib`
- `Pillow`
- `opencv-contrib-python` optional, but recommended for real AprilTag image generation

Install the dependencies with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install numpy matplotlib pillow opencv-contrib-python
```

If OpenCV AprilTag support is not available:

- the script will still run by default
- it will generate deterministic placeholder tag images instead of true AprilTags
- use `--strict_apriltag` to fail fast instead of allowing placeholders

## Quick Start

Run the included example configuration:

```bash
python3 generate_camera_mesh_and_apriltag_boards.py \
  --field_width_ft 96 \
  --field_height_ft 27 \
  --cam_width_ft 14 \
  --cam_height_ft 7 \
  --overlap_x_ratio 0.16 \
  --overlap_y_ratio 0.20 \
  --min_edge_margin_ft 1.0 \
  --target_overlap_x_ft 2.0 \
  --target_overlap_y_ft 2.0 \
  --coord_step_ft 0.5 \
  --board_width_ft 2 \
  --board_height_ft 2 \
  --tag_size_in 8 \
  --plan_camera_label_fontsize 12 \
  --board_near_camera_fontsize 18 \
  --output_dir demo_output
```

For the included demo configuration, the generated layout contains:

- 40 cameras
- 28 boards
- 112 unique AprilTag IDs

## Example Output Layout

```text
output_dir/
├── boards/
│   ├── B01.pdf
│   ├── B01.png
│   ├── ...
├── boards_tiled/              # only when --tiled_output is enabled
├── boards_combined.pdf
├── boards_manifest.csv
├── boards_manifest.pdf
├── camera_layout_plan.pdf
├── camera_layout_plan.png
├── cameras_manifest.csv
├── visibility_boards.csv
└── visibility_cameras.csv
```

## Key Inputs

### Field and camera geometry

- `--field_width_ft`, `--field_height_ft`
  - physical field dimensions in feet
- `--cam_width_ft`, `--cam_height_ft`
  - width and height of the effective camera footprint on the field, in feet
- `--overlap_x_ratio`, `--overlap_y_ratio`
  - requested fractional overlap between adjacent camera views
- `--target_overlap_x_ft`, `--target_overlap_y_ft`
  - preferred overlap widths in feet
- `--min_edge_coverage_ratio`
  - preferred amount of camera coverage extending beyond the field boundary
- `--min_edge_margin_ft`
  - hard minimum overflow margin beyond each field edge
- `--coord_step_ft`
  - snap grid for camera centers and board lower-left coordinates

### Board placement

- `--board_width_ft`, `--board_height_ft`
  - physical board size in feet
- `--board_offset_x_ft`, `--board_offset_y_ft`
  - optional board placement offsets from the midpoint between adjacent camera centers
- `--start_tag_id`
  - starting ID for tag assignment
- `--april_family`
  - supported by the OpenCV backend: `tag16h5`, `tag25h9`, `tag36h10`, `tag36h11`
- `--tags_per_board`
  - currently fixed at `4`

### Print layout

- `--tag_size_in`
  - exact printed size for each tag in inches
- `--min_tag_size_in`
  - minimum acceptable tag size if `--tag_size_in` is omitted
- `--tag_gap_in`
  - spacing between the four tags
- `--board_inner_margin_in`
  - inner margin between tag area and board edge
- `--header_height_in`, `--footer_height_in`
  - reserved space for labels and instructions
- `--board_png_dpi`
  - PNG export resolution

### Optional extras

- `--tiled_output`
  - generate multi-page poster PDFs for large-format printing from standard paper
- `--tile_page_size`, `--tile_page_width_in`, `--tile_page_height_in`
  - tile page settings
- `--tile_overlap_in`
  - overlap between poster tiles
- `--tile_dpi`
  - poster tiling raster DPI
- `--plan_line_labels` or `--no-plan_line_labels`
  - turn field coordinate guide lines on or off in the layout plan
- `--plan_line_label_fontsize`, `--plan_line_decimals`
  - format global plan coordinate labels
- `--plan_camera_label_fontsize`
  - camera label font size in the layout plan
- `--board_near_camera_fontsize`
  - size of `near Cxx` labels on each printed board
- `--strict_apriltag`
  - require a real AprilTag backend instead of placeholders

See the full CLI for all options:

```bash
python3 generate_camera_mesh_and_apriltag_boards.py --help
```

## CSV Outputs

### `cameras_manifest.csv`

One row per camera, including:

- camera ID
- row and column index in the mesh
- center coordinates
- bounding box extents

### `boards_manifest.csv`

One row per board, including:

- board ID
- lower-left installation coordinate in feet
- row and column index
- four assigned tag IDs

### `visibility_boards.csv`

For each board:

- how many cameras overlap its footprint
- which cameras can see it

### `visibility_cameras.csv`

For each camera:

- how many boards overlap its footprint
- which boards it can see

## Practical Notes

- Boards are placed at internal intersections between adjacent camera views, not on the outer boundary.
- Tag IDs are unique across all boards.
- The script warns if some edge cameras do not overlap any board footprint.
- Overlap ratios outside `0.10` to `0.30` are allowed, but the script prints a warning.
- If the requested geometry and constraints cannot produce a valid mesh, the script exits with a descriptive error.

## Current Implementation Caveats

These are worth knowing before publishing or using the tool:

- `--tags_per_board` is currently hard-limited to `4`.
- Board outputs are rendered on a canvas equal to the physical board size in inches. For example, a `2 ft x 2 ft` board becomes a `24 in x 24 in` page/canvas.
- The CLI accepts `--board_page_size`, `--board_page_width_in`, and `--board_page_height_in`, but the current implementation renders per-board outputs using the physical board size instead of those page-size arguments.
- Without `opencv-contrib-python`, generated tags are placeholders unless `--strict_apriltag` is enabled.

## Repository Contents

- [`generate_camera_mesh_and_apriltag_boards.py`](generate_camera_mesh_and_apriltag_boards.py): main CLI tool
- [`README.md`](README.md): project documentation
- [`demo_output/`](demo_output): sample generated artifacts

## Typical Workflow

1. Measure the field dimensions.
2. Estimate each camera's effective footprint on the ground plane.
3. Choose overlap targets and edge-margin policy.
4. Run the script and review `camera_layout_plan.pdf`.
5. Verify the board count and coordinates in `boards_manifest.csv`.
6. Print the board PDFs or tiled posters.
7. Install each board at its listed lower-left coordinate.

## License

No license file is currently included in this repository. Add one before publishing publicly if you want to permit reuse.
