#!/usr/bin/env python3
"""Generate 10-inch tag36h11 vector tags, portrait Tabloid, top 13-inch cutout.
Requires opencv-contrib-python. Default: existing IDs 1-20; --both-walls uses
100-119 and 200-219 from the room plan. Board must be matte white, 13x13 in.
"""
import argparse
import csv
import json
from pathlib import Path
import cv2
PT=72

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
        objs.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 1224] /CropBox [0 0 792 1224] '
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


def page(tag_id, index, wall):
    station=12+24*index
    room_x=station if wall!='B' else 480-station
    c=['1 g',rect(0,0,11,17),'0 g','0 G']
    d=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    bits=cv2.aruco.generateImageMarker(d,tag_id,8)
    # Center tag on retained 11x13 paper: 0.5 inch from paper sides,
    # 1.5 inches from retained top/bottom; white board adds 1 inch per side.
    for r in range(8):
        for col in range(8):
            if bits[r,col]==0:
                c.append(rect(.5+col*1.25,5.5+(7-r)*1.25,1.25,1.25))
    # Retained band at 12.75-13 inches from top: outside 1.25-inch quiet zone.
    c += ['0.75 G','0.75 g','0.3 w',line(.25,4,10.75,4)]
    start=station-5.5
    for eighth in range(89):
        x=eighth/8
        tick=.10 if eighth%8==4 else (.075 if eighth%4==0 else .045)
        c.append(line(x,4,x,4+tick))
        position=start+x
        if position.is_integer() and 1<=x<=10:
            label=f'{int(position)//12}\'{int(position)%12}"'
            c.append(text(x-.14,4.12,label,6))
    c.append(text(.35,4.12,f'ID {tag_id}',6))
    # Everything else is removed with the lower four inches.
    c += ['0 g',text(.5,3.25,f'10-inch tag36h11 | ID {tag_id} | '+('Wall '+wall if wall else 'Existing IDs 1-20'),16),
          text(.5,2.86,'TABLOID 11 x 17 / PORTRAIT / ACTUAL SIZE 100% / SINGLE-SIDED',11),
          text(.5,2.5,'Cut at the faint ruler line: KEEP TOP 13 inches; DISCARD BOTTOM 4 inches.',11),
          text(.5,2.14,'Center the 11 x 13-inch paper on a MATTE WHITE 13 x 13-inch board.',11),
          text(.5,1.78,'Leave 1 inch of white board exposed on each side. Tag center = board center.',11),
          text(.5,1.42,f'Placement: center at tape station {station//12}ft {station%12}in; centers spaced 24 inches.',11),
          text(.5,1.06,f'Nominal room X = {room_x} inches. '+('Wall B station increases opposite room X.' if wall=='B' else 'Station increases with room X.'),10),
          text(.5,.7,'Check black square = 10 x 10 inches. Check ruler against real tape. Keep paper flat.',10)]
    return c,dict(tag_id=tag_id,wall=wall or 'unspecified',family='tag36h11',tag_size_in=10,
                  tape_station_center_in=station,nominal_room_x_in=room_x,
                  nominal_room_y_in=(276 if wall=='B' else 0) if wall else None,
                  installed_z_in=None,board_size_in=[13,13],paper_cutout_in=[11,13],
                  page_tag_center_in=[5.5,10.5],cut_y_from_bottom_in=4)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--both-walls',action='store_true')
    p.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parent/'tabloid_10in_portrait_13in_board')
    a=p.parse_args()
    a.output_dir.mkdir(parents=True,exist_ok=True)
    specs=[('A',100),('B',200)] if a.both_walls else [('',1)]
    pages,records=[],[]
    for wall,start in specs:
        subset=[]
        for i in range(20):
            c,r=page(start+(19-i if wall=='B' else i),i,wall)
            subset.append(c); records.append(r)
        name=f'wall_{wall}_10in_portrait.pdf' if wall else 'tabloid_tags_1-20_portrait.pdf'
        pdf(a.output_dir/name,subset)
        pages+=subset
    if a.both_walls:
        pdf(a.output_dir/'both_walls_10in_portrait.pdf',pages)
    (a.output_dir/'layout.json').write_text(json.dumps(dict(status='Nominal print layout; survey before use',ruler_gray=.75,tags=records),indent=2)+'\n')
    with (a.output_dir/'layout.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=records[0].keys()); w.writeheader(); w.writerows(records)
    print(f'Created {len(pages)} pages in {a.output_dir}')


if __name__=='__main__':
    main()
