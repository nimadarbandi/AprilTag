#!/usr/bin/env python3
"""Exact vector Letter PDFs: 4-inch tag36h11 tags on 6-inch tape strips.
Requires numpy and opencv-contrib-python. No PDF library required.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import cv2

PT = 72
PAGE = (792, 612)


def text(x, y, s, size=10):
    s = s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'BT /F1 {size} Tf {x*PT:.5f} {y*PT:.5f} Td ({s}) Tj ET'


def line(x, y, xx, yy):
    return f'{x*PT:.5f} {y*PT:.5f} m {xx*PT:.5f} {yy*PT:.5f} l S'


def rect(x, y, w, h):
    return f'{x*PT:.5f} {y*PT:.5f} {w*PT:.5f} {h*PT:.5f} re f'


def pdf(path, pages):
    objs = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for commands in pages:
        page_id = len(objs)+1
        kids.append(f'{page_id} 0 R')
        stream = ('\n'.join(commands)+'\n').encode('ascii')
        objs.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] /CropBox [0 0 792 612] '
                     f'/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id+1} 0 R >>').encode())
        objs.append(f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'endstream')
    objs[0] = b'<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /PrintScaling /None /Duplex /Simplex >> >>'
    objs[1] = f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(kids)}] >>'.encode()
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref = len(out)
    out.extend(f'xref\n0 {len(objs)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        out.extend(f'{offset:010d} 00000 n \n'.encode())
    out.extend(f'trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(out)


def feet(inches):
    f = int(inches//12)
    i = inches-f*12
    return f'{f}ft {i:g}in'


def make_page(wall, p, count, wall_length, dictionary, next_id, records):
    start = p*11
    length = min(11, wall_length-start)
    end = start+length
    c = ['1 g', rect(0, 0, 11, 8.5), '0 g', '0 G', '0.5 w']
    c += [text(.35, 1.92, f'WALL {wall}  |  SHEET {p+1:02d}/{count:02d}  |  4-inch AprilTags / 6-inch tape strip', 17),
          text(.35, 1.57, f'TAPE STATION: {feet(start)} to {feet(end)}.  Print LETTER LANDSCAPE, ACTUAL SIZE / 100%.', 11),
          text(.35, 1.24, 'CUT at the ruler baseline above. KEEP the top 6 inches; discard this bottom 2.5-inch band.', 11),
          text(.35, .94, 'Keep factory left/right edges. Butt sheets together without overlap. Align ruler to a real tape measure.', 10),
          text(.35, .64, 'Check: black tag = 4 x 4 inches; ruler ticks = 1 inch. Keep paper flat; no stretching, folds, or glossy cover.', 10)]
    direction = 'Start at room X=0; printed left-to-right follows room +X.' if wall == 'A' else f'Start at room X={wall_length:g}in; printed left-to-right follows room -X.'
    c += [text(.35, .32, direction, 10)]
    c += ['0.35 G', '0.45 w', '[3 2] 0 d', line(.25, 2.5, 10.75, 2.5), '[] 0 d', '0 G']
    # Ruler is above cut line, outside all tag quiet zones; 1/8-inch divisions.
    for eighth in range(int(math.ceil(start*8)), int(math.floor(end*8))+1):
        station = eighth/8
        x = station-start
        # Edge ticks may be clipped by a non-borderless printer; the factory edge is the datum.
        if eighth % 8 == 0:
            tick = .34 if eighth % 96 == 0 else .26
        elif eighth % 4 == 0:
            tick = .20
        elif eighth % 2 == 0:
            tick = .14
        else:
            tick = .09
        c.append(line(x, 2.5, x, 2.5+tick))
        if eighth % 8 == 0 and .35 <= x <= min(length-.35, 10.65):
            label = f'{int(station)//12}\'{int(station)%12}"'
            c.append(text(x-.16, 2.94, label, 8))
    for local_x in (2.75, 8.25):
        # Include only tags whose complete 0.5-inch white margin fits the final strip.
        if local_x+2.5 > length:
            continue
        tag_id = next_id
        next_id += 1
        bits = cv2.aruco.generateImageMarker(dictionary, tag_id, 8)
        assert bits.shape == (8, 8)
        x0, y0 = local_x-2, 3.75
        c.append('0 g')
        for r in range(8):
            for col in range(8):
                if bits[r, col] == 0:
                    c.append(rect(x0+col*.5, y0+(7-r)*.5, .5, .5))
        station = start+local_x
        room_x = station if wall == 'A' else wall_length-station
        c.append(text(local_x-2.35, 3.10, f'{wall} | ID {tag_id} | X {room_x:g}in | station {feet(station)} | UP', 8))
        records.append(dict(wall=wall, page=p+1, tag_id=tag_id, family='tag36h11', tag_size_in=4,
                            tape_station_in=station, nominal_room_x_in=room_x,
                            nominal_room_y_in=0 if wall=='A' else 276,
                            installed_center_z_in=None, center_above_strip_bottom_in=3.25,
                            page_center_x_in=local_x, page_center_y_in=5.75,
                            face_normal_room_y=1 if wall=='A' else -1))
    if length < 11:
        c += ['0.45 G', '[4 3] 0 d', line(length, 2.5, length, 8.25), '[] 0 d', '0 G',
              text(length+.2, 5.5, 'DISCARD', 13), text(length+.2, 5.2, 'Right of 40-ft cut', 10),
              text(.35, 2.26, f'FINAL SHEET: also cut vertically at local {length:g}in (tape station {feet(end)}).', 9)]
    return c, next_id


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent/'letter_4in_tape_6in')
    ap.add_argument('--start-id', type=int, default=400)
    args = ap.parse_args()
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    if not 0 <= args.start_id <= len(dictionary.bytesList)-174:
        ap.error('Need 174 consecutive valid tag36h11 IDs (default: 400-573).')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records, all_pages = [], []
    next_id = args.start_id
    for wall in ('A', 'B'):
        pages=[]
        for p in range(44):
            commands, next_id = make_page(wall, p, 44, 480, dictionary, next_id, records)
            pages.append(commands)
        pdf(args.output_dir/f'wall_{wall}_40ft_letter_4in_tags.pdf', pages)
        all_pages += pages
    pdf(args.output_dir/'both_walls_40ft_letter_4in_tags.pdf', all_pages)
    metadata = dict(status='PROPOSED PRINT LAYOUT; survey installed positions before localization',
                    paper_inches=[11, 8.5], retained_strip_height_in=6, cut_y_from_bottom_in=2.5, retained_page_region="top",
                    ruler_division_in=.125, wall_length_in=480, nominal_room_width_in=276,
                    pages_per_wall=44, tags_per_wall=87, family='tag36h11',
                    note='Wall B tape station increases opposite room X. Height unknown. All tags printed top-up.',
                    tags=records)
    (args.output_dir/'tag_layout.json').write_text(json.dumps(metadata, indent=2)+'\n')
    with (args.output_dir/'tag_layout.csv').open('w', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f'Created 88 pages, 174 unique tags, IDs {args.start_id}-{next_id-1} in {args.output_dir}')


if __name__ == '__main__':
    main()
