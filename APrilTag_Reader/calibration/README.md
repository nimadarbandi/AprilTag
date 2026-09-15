# Printable checkerboard

## 40 × 24 inch matte-roll target — recommended

`checkerboard_11x6_inner_3in_40x24_matte.pdf` and its editable SVG are the recommended targets for the available 24-inch matte roll. The page is exactly **40 × 24 inches** and contains **11 × 6 inner corners** (12 × 7 physical squares). Every square is exactly **3 inches / 76.2 mm**. The checker pattern is 36 × 21 inches, centered with 2-inch left/right margins and 1.5-inch top/bottom margins. The detected inner-corner span is 30 × 15 inches.

Ask the print shop for **100% / Actual Size** with all Fit, Shrink, and Scale-to-Page options disabled. Mount it completely flat and verify several horizontal and vertical squares measure exactly 3 inches after mounting.

```python
checkerboard_inner_corners = (11, 6)
square_size_mm = 76.2
```

## 40 × 30 inch ceiling-camera target

`checkerboard_9x6_inner_3.75in_40x30.pdf` and its editable SVG are the recommended large-format targets for the Swann 1080p ceiling cameras. The page is exactly **40 × 30 inches** and contains **9 × 6 inner corners** (10 × 7 physical squares). Every square is exactly **3.75 inches / 95.25 mm**. The checker pattern is 37.5 × 26.25 inches, centered with a clean white border.

Ask the print shop for **100% / Actual Size** with all Fit, Shrink, and Scale-to-Page options disabled. Use matte paper or matte adhesive material, mount it completely flat, and verify several horizontal and vertical squares measure exactly 3.75 inches after mounting.

```python
checkerboard_inner_corners = (9, 6)
square_size_mm = 95.25
```

`checkerboard_9x6_inner_25mm_A4_landscape.svg` is an OpenCV calibration target with **9 × 6 inner corners** (10 × 7 squares). Each square is **25.00 mm** (0.9843 in) and the complete checkerboard is **250 × 175 mm** (9.84 × 6.89 in).

Print it on A4 paper in landscape orientation using **Actual Size / 100% scale**. Turn off “Fit to Page”, “Scale to Fit”, and any automatic margin scaling. Measure several squares after printing; they must each be 25.00 mm. Mount the page flat on rigid cardboard or foam board before taking calibration images.

For OpenCV, use:

```python
checkerboard_inner_corners = (9, 6)
square_size_mm = 25.0
```

If you print on US Letter paper, use the printer's 100% setting only after confirming the full 297 mm-wide A4 page is not clipped; A4 paper is recommended for this exact file.

## 8 × 8 inch rover box faces

For the 8 × 8 inch rover viewed by the Swann 1080p ceiling cameras from approximately 3 m, use `checkerboard_5x5_inner_32mm_8in_face_3m.svg`. Print **three identical copies**: one for the horizontal top and one for each vertical side. This long-range target has **5 × 5 inner corners** (6 × 6 squares), with exactly **32.00 mm** (1.2598 in) per square. The checkerboard is 192 × 192 mm (7.559 × 7.559 in), leaving a 5.60 mm (0.220 in) white border on every edge.

For OpenCV and the calibration website, use:

```python
checkerboard_inner_corners = (5, 5)
square_size_mm = 32.0
```

This pattern trades some corner count for squares that are 60% larger than the original 20 mm design, making complete-pattern detection more reliable at the 3 m working distance. Compensate for the lower per-image corner count by retaining 30–40 sharp, geometrically varied images per camera.

Print the SVG on **US Letter paper at Actual Size / 100%**, with Fit to Page, Scale to Fit, and automatic enlargement disabled. Extra paper surrounds the centered target. Cut through the **center of the thin gray rectangle**; that centerline is exactly 203.20 × 203.20 mm, producing a finished **8.000 × 8.000 inch** target. After printing, verify several squares measure exactly **32.00 mm** in both directions and verify opposite cutting-line centerlines are 8 inches apart. Mount it perfectly flat on a rigid face without wrinkles, bubbles, glossy covering, or curled edges.

The older `checkerboard_8x8_inner_20mm_8in_face.svg` remains available for compatibility with existing captures. Do not mix images of the 20 mm/8×8 pattern and the new 32 mm/5×5 pattern in one calibration run. Your detector settings must match the target being photographed.

### Older close-range rover target

The earlier target has **8 × 8 inner corners** (9 × 9 squares), with exactly **20.00 mm** (0.7874 in) per square. Use these settings only with that older SVG:

For OpenCV, use:

```python
checkerboard_inner_corners = (8, 8)
square_size_mm = 20.0
```

Print at **Actual Size / 100%** with no fit-to-page scaling. Check several mounted squares with a ruler or caliper; each must measure 20.00 mm before you capture calibration footage.
