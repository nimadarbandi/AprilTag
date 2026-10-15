#!/usr/bin/env python3
"""Create portrait Letter pages for 8-inch tag36h11 tags.

Produces two ID batches, IDs 100-119 and IDs 200-219, one tag per page.
The ruler runs the full physical page width (edge to edge) rather than
being inset 0.5 inch, per explicit instruction to use the whole paper
width as the print-scale reference.
"""

from pathlib import Path

import cv2


PT = 72
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
RETAINED_HEIGHT_IN = 9.5
CUT_Y_IN = PAGE_HEIGHT_IN - RETAINED_HEIGHT_IN
TAG_SIZE_IN = 8.0
CELL_IN = TAG_SIZE_IN / 8
TAG_X_IN = (PAGE_WIDTH_IN - TAG_SIZE_IN) / 2
TAG_Y_IN = 2.5
OUTPUT_ROOT = Path(__file__).resolve().parent / "_Outputs"

ID_BATCHES = [(100, 120), (200, 220)]


def text(x: float, y: float, value: str, size: int = 10) -> str:
    value = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 {size} Tf {x*PT:.5f} {y*PT:.5f} Td ({value}) Tj ET"


def line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"{x1*PT:.5f} {y1*PT:.5f} m {x2*PT:.5f} {y2*PT:.5f} l S"


def rect(x: float, y: float, width: float, height: float) -> str:
    return f"{x*PT:.5f} {y*PT:.5f} {width*PT:.5f} {height*PT:.5f} re f"


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_refs: list[str] = []
    for commands in pages:
        page_id = len(objects) + 1
        page_refs.append(f"{page_id} 0 R")
        stream = ("\n".join(commands) + "\n").encode("ascii")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/CropBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")

    objects[0] = (
        b"<< /Type /Catalog /Pages 2 0 R "
        b"/ViewerPreferences << /PrintScaling /None /Duplex /Simplex >> >>"
    )
    objects[1] = f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(page_refs)}] >>".encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def make_page(tag_id: int, dictionary) -> list[str]:
    commands = ["1 g", rect(0, 0, PAGE_WIDTH_IN, PAGE_HEIGHT_IN), "0 g", "0 G", "0.5 w"]

    # OpenCV returns the complete 8x8 tag36h11 marker (black border included).
    # At 8 inches each marker cell is CELL_IN (1.0in) wide.
    bits = cv2.aruco.generateImageMarker(dictionary, tag_id, 8)
    assert bits.shape == (8, 8)
    for row in range(8):
        for column in range(8):
            if bits[row, column] == 0:
                commands.append(
                    rect(
                        TAG_X_IN + column * CELL_IN,
                        TAG_Y_IN + (7 - row) * CELL_IN,
                        CELL_IN,
                        CELL_IN,
                    )
                )

    # Ruler runs the full physical page width, edge to edge, as the
    # print-scale reference (a longer baseline catches scaling error more
    # precisely than an inset one; borderless printing may be required for
    # the very edge ticks to render).
    ruler_left = 0.0
    ruler_right = PAGE_WIDTH_IN
    ruler_len_in = ruler_right - ruler_left
    n_eighths = round(ruler_len_in * 8)
    commands += [
        "0.35 G", "0.45 w", "[3 2] 0 d",
        line(ruler_left, CUT_Y_IN, ruler_right, CUT_Y_IN),
        "[] 0 d", "0 G",
    ]
    for eighth in range(n_eighths + 1):
        x = ruler_left + eighth / 8
        if eighth % 8 == 0:
            tick_height = 0.34
        elif eighth % 4 == 0:
            tick_height = 0.22
        elif eighth % 2 == 0:
            tick_height = 0.15
        else:
            tick_height = 0.10
        commands.append(line(x, CUT_Y_IN, x, CUT_Y_IN + tick_height))
        if eighth % 8 == 0:
            inch = eighth // 8
            label_x = x - 0.06 if 0 < inch < ruler_len_in else max(x, 0.02) if inch == 0 else x - 0.14
            commands.append(text(label_x, CUT_Y_IN + 0.43, str(inch), 8))

    commands += [
        text(TAG_X_IN + TAG_SIZE_IN / 2 - 0.85, TAG_Y_IN - 0.42, f"tag36h11 | ID {tag_id} | UP", 10),
        text(0.55, 1.05, "CUT on the ruler baseline. KEEP the upper 8.5 x 9.5-inch section.", 10),
        text(0.55, 0.70, "Print US LETTER PORTRAIT, ACTUAL SIZE / 100%. Do not Fit or Scale.", 9),
        text(0.55, 0.36, f"Check before printing all pages: black square exactly {TAG_SIZE_IN:g} x {TAG_SIZE_IN:g} inches.", 8),
    ]
    return commands


def main() -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    for start, stop in ID_BATCHES:
        pages = [make_page(tag_id, dictionary) for tag_id in range(start, stop)]
        out_dir = OUTPUT_ROOT / f"letter_portrait_8in_ids_{start}_{stop - 1}"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"letter_portrait_8in_tag36h11_ids_{start}_{stop - 1}.pdf"
        write_pdf(output_path, pages)
        print(f"Created {len(pages)} portrait Letter pages at {output_path}")


if __name__ == "__main__":
    main()
