# Run Examples

## 1) Generate full camera mesh + printable boards
```bash
python generate_camera_mesh_and_apriltag_boards.py \
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

## 2) Re-render layout from manifests
```bash
python update_layout.py --output-dir demo_output
```

No DVR overlay:
```bash
python update_layout.py --output-dir demo_output --no-dvr
```

## 3) Prepare robot AprilTags (face sheets + individual tags)
```bash
python prepare_robot_apriltags.py \
  --output-dir robot \
  --april-family tag36h11 \
  --start-tag-id 300 \
  --cube-face-size-in 12 \
  --paper-size-in 8 \
  --tag-size-in 7 \
  --dpi 300
```

## 4) Reuse printed boards for a new field + auto camera suggestion + DVR assignment
```bash
python plan_reuse_layout_with_dvrs.py \
  --field_width_ft 40 \
  --field_height_ft 23 \
  --cam_width_ft 14 \
  --cam_height_ft 7 \
  --min_edge_margin_ft 1.0 \
  --target_overlap_x_ft 2.0 \
  --target_overlap_y_ft 2.0 \
  --coord_step_ft 0.5 \
  --board_width_ft 2 \
  --board_height_ft 2 \
  --num_dvrs 2 \
  --render_layout \
  --output_dir reuse_40x23_dvr
```

Force camera grid:
```bash
python plan_reuse_layout_with_dvrs.py \
  --field_width_ft 80 \
  --field_height_ft 23 \
  --cam_width_ft 14 \
  --cam_height_ft 7 \
  --min_edge_margin_ft 1.0 \
  --target_overlap_x_ft 2.0 \
  --target_overlap_y_ft 2.0 \
  --coord_step_ft 0.5 \
  --board_width_ft 2 \
  --board_height_ft 2 \
  --num_cam_cols 7 \
  --num_cam_rows 5 \
  --num_dvrs 4 \
  --max_cams_per_dvr 10 \
  --numbering_order vertical \
  --layout_title "Reuse Layout 80x23 (Site Visit v2)" \
  --render_layout \
  --output_dir reuse_80x23_dvr
```


python plan_reuse_layout_with_dvrs.py \
  --field_width_ft 40 \
  --field_height_ft 23 \
  --cam_width_ft 12 \
  --cam_height_ft 5 \
  --min_edge_margin_ft 1.0 \
  --target_overlap_x_ft 2.0 \
  --target_overlap_y_ft 1.0 \
  --coord_step_ft 0.5 \
  --board_width_ft 2 \
  --board_height_ft 2 \
  --num_dvrs 2 \
  --numbering_order vertical \
  --layout_title "Layout 40x23 - 2meter Camera Height" \
  --max_cams_per_dvr 12 \
  --render_layout \
  --output_dir reuse_40x23
```

## 5) Generate measured US Letter pages for individual tags

This creates one clean `tag36h11` marker per landscape page, inclusive of both
IDs. Each tag is exactly 8 × 8 inches with 0.25 inch of white space on all four
sides. The resulting 8.5 × 8.5 inch target area occupies the left side of the
11 × 8.5 inch sheet. The right strip shows the tag ID and a large UP arrow;
both remain separated from the tag's quiet border. There are no rulers.

```bash
python generate_letter_apriltag_pages.py \
  --start-id 9 \
  --end-id 25 \
  --output letter_tags_0009_to_0025.pdf
```

Print in **landscape orientation** on US Letter paper using **Actual Size /
100%**. Disable Fit to Page and all automatic scaling. The printed AprilTag
outer size is exactly 8 inches; the white border is not part of `tag_size`.
