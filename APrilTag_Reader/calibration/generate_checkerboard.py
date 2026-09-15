#!/usr/bin/env python3
"""Generate exact-size vector tabloid calibration targets using the standard library."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
PT_PER_MM = 72 / 25.4
PAGE_W_MM, PAGE_H_MM = 431.8, 279.4
SQUARE_MM = 30.0
COLS, ROWS = 12, 7  # Actual squares; 11 x 6 inner corners.
X_MM = (PAGE_W_MM - COLS * SQUARE_MM) / 2
Y_MM = (PAGE_H_MM - ROWS * SQUARE_MM) / 2
NAME = 'checkerboard_11x6_inner_30mm_tabloid_17x11'


def pt(mm):
    return mm * PT_PER_MM


def pdf(path, commands, title):
    stream = ('\n'.join(commands) + '\n').encode('ascii')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /PrintScaling /None >> >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1224 792] /CropBox [0 0 1224 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'endstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        f'<< /Title ({title}) /Creator (Camera Bench exact-size vector target generator) >>'.encode(),
    ]
    output = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(output)
    output.extend(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(output)


def rect(x, y, width, height):
    return f'{pt(x):.8f} {pt(y):.8f} {pt(width):.8f} {pt(height):.8f} re f'


def line(x1, y1, x2, y2):
    return f'{pt(x1):.8f} {pt(y1):.8f} m {pt(x2):.8f} {pt(y2):.8f} l S'


def label(x, y, message, size=12):
    escaped = message.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'BT /F1 {size} Tf {pt(x):.8f} {pt(y):.8f} Td ({escaped}) Tj ET'


def main():
    commands = ['1 g', '0 0 1224 792 re f', '0 g']
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W_MM}mm" height="{PAGE_H_MM}mm" viewBox="0 0 {PAGE_W_MM} {PAGE_H_MM}">',
           '<title>11 x 6 inner corners; 30 mm squares; tabloid landscape; print at 100 percent</title>',
           '<rect width="100%" height="100%" fill="white"/>', '<g fill="black">']
    for row in range(ROWS):
        for col in range(COLS):
            if (row + col) % 2 == 0:
                x, y = X_MM + col * SQUARE_MM, Y_MM + row * SQUARE_MM
                commands.append(rect(x, PAGE_H_MM - y - SQUARE_MM, SQUARE_MM, SQUARE_MM))
                svg.append(f'<rect x="{x:.8f}" y="{y:.8f}" width="30" height="30"/>')
    svg.extend(['</g>', '</svg>'])
    pdf(ROOT / f'{NAME}.pdf', commands, '11x6 inner checkerboard - 30mm squares - 17x11 inch tabloid')
    (ROOT / f'{NAME}.svg').write_text('\n'.join(svg) + '\n')
    metadata = {
        'pattern': 'checkerboard', 'inner_corners': {'columns': 11, 'rows': 6},
        'squares': {'columns': COLS, 'rows': ROWS}, 'nominal_square_size_mm': SQUARE_MM,
        'pattern_width_mm': COLS * SQUARE_MM, 'pattern_height_mm': ROWS * SQUARE_MM,
        'paper': {'name': 'US Tabloid / ANSI B', 'orientation': 'landscape', 'width_mm': PAGE_W_MM,
                  'height_mm': PAGE_H_MM, 'pdf_width_points': 1224, 'pdf_height_points': 792},
        'white_border_mm': {'left': X_MM, 'right': X_MM, 'top': Y_MM, 'bottom': Y_MM},
        'printing': 'Actual size / 100 percent; no fit-to-page. Measure physical squares horizontally and vertically.',
        'app': 'Create NEW camera/lens/focus profiles. Select 11 x 6 corners and enter measured square size, nominally 30 mm.',
    }
    (ROOT / f'{NAME}.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # Separate page keeps the checkerboard's white border completely clear.
    check = ['1 g', '0 0 1224 792 re f', '0 g', '0 G', '0.6 w',
             label(25, 252, 'PRINT SCALE CHECK - US TABLOID 17 x 11 inches', 18),
             label(25, 239, 'Use the same printer settings as the checkerboard: landscape, Actual size / 100%, one page per sheet.'),
             label(25, 230, 'Measure between endpoint tick centres. Both lines must measure 100 mm; the box must be 30 x 30 mm.'),
             line(40, 195, 140, 195), line(40, 192, 40, 198), line(140, 192, 140, 198),
             label(66, 202, '100 mm horizontal'),
             line(210, 95, 210, 195), line(207, 95, 213, 95), line(207, 195, 213, 195),
             label(218, 145, '100 mm vertical'),
             f'{pt(300):.8f} {pt(160):.8f} {pt(30):.8f} {pt(30):.8f} re S',
             label(296, 151, '30 x 30 mm'),
             label(25, 75, 'Also verify the ACTUAL checkerboard after printing and mounting:'),
             label(25, 64, 'Five square widths = 150 mm. Five square heights = 150 mm. Measure both directions.'),
             label(25, 53, 'Full pattern = 360 mm wide x 210 mm tall. There are 12 x 7 squares and 11 x 6 inner corners.'),
             label(25, 42, 'If horizontal and vertical scale differ, or spacing varies across the sheet, correct the print and reprint.'),
             label(25, 31, 'Use a rigid flat backing and matte paper. Do not use this scale-check page as the calibration target.')]
    pdf(ROOT / 'print_scale_check_tabloid.pdf', check, 'Tabloid printer scale verification - 100mm horizontal and vertical')
    print(ROOT / f'{NAME}.pdf')


if __name__ == '__main__':
    main()
