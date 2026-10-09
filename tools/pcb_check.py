#!/usr/bin/env python3
"""Experimental two-layer copper audit; not electrical or full Gerber DRC."""
from __future__ import annotations
import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

@dataclass
class Copper:
    id: str
    kind: str
    net: str
    layer: int
    geometry: object
    terminal: bool = False
    bridge: bool = False


def source_copper(board):
    copper, skipped = [], []
    def add(obj, kind, geom, layers, terminal=False, bridge=False):
        if geom.is_empty or not geom.is_valid:
            skipped.append({'id': obj.get('id'), 'reason': 'invalid/empty geometry'})
            return
        if not obj.get('net'):
            skipped.append({'id': obj.get('id'), 'reason': 'unnamed copper net'})
            return
        for layer in layers:
            copper.append(Copper(str(obj['id']), kind, str(obj['net']), layer, geom, terminal, bridge))
    for track in board.get('tracks', []):
        points = track.get('points', [])
        if track.get('layer') not in (1, 2): continue
        if len(points) < 2 or track.get('width', 0) <= 0:
            skipped.append({'id': track.get('id'), 'reason': 'unsupported track'})
            continue
        add(track, 'track', LineString(points).buffer(track['width']/2, quad_segs=32), [track['layer']])
    for pad in board.get('pads', []):
        w, h = float(pad['width']), float(pad['height'])
        shape = pad['shape'].upper()
        if w <= 0 or h <= 0 or shape not in ('RECT', 'ELLIPSE', 'OVAL') or pad['layer'] not in (1, 2, 11):
            skipped.append({'id': pad.get('id'), 'reason': 'unsupported pad'})
            continue
        if shape == 'RECT': geom = box(-w/2, -h/2, w/2, h/2)
        elif shape == 'ELLIPSE': geom = affinity.scale(Point(0, 0).buffer(1, quad_segs=64), w/2, h/2)
        elif w >= h: geom = LineString([(-(w-h)/2, 0), ((w-h)/2, 0)]).buffer(h/2, quad_segs=64) if w > h else Point(0,0).buffer(w/2,quad_segs=64)
        else: geom = LineString([(0, -(h-w)/2), (0, (h-w)/2)]).buffer(w/2, quad_segs=64)
        geom = affinity.rotate(geom, float(pad.get('rotation', 0)), origin=(0,0))
        geom = affinity.translate(geom, pad['x'], pad['y'])
        drill = float(pad.get('drill') or 0)
        if drill: geom = geom.difference(Point(pad['x'],pad['y']).buffer(drill/2,quad_segs=64))
        through = pad['layer'] == 11
        add(pad, 'pad', geom, [1,2] if through else [pad['layer']], True, through and pad.get('plated') == 'Y' and drill > 0)
    for via in board.get('vias', []):
        point = Point(via['x'],via['y'])
        geom = point.buffer(via['diameter']/2,quad_segs=64)
        if via.get('drill'): geom = geom.difference(point.buffer(via['drill']/2,quad_segs=64))
        add(via, 'via', geom, [1,2], False, True)
    for graphic in board.get('graphics', []):
        if graphic.get('layer') not in (1,2): continue
        kind = graphic.get('kind')
        if kind in ('text',):
            skipped.append({'id':graphic.get('id'),'reason':'copper text not interpreted'})
            continue
        if kind == 'copper-area':
            skipped.append({'id':graphic.get('id'),'reason':'unresolved pour: boundary is not filled copper'})
            continue
        if kind not in ('rect','solid-region'): continue
        if kind == 'solid-region' and graphic.get('sourceRaw','').split('~')[4:5] == ['cutout']:
            skipped.append({'id':graphic.get('id'),'reason':'cutout subtraction not resolved'})
            continue
        points = graphic.get('pointsMM', [])
        if len(points)<3 or not graphic.get('net'):
            skipped.append({'id':graphic.get('id'),'reason':'unsupported region or unnamed net'})
            continue
        # No repair buffer(0): invalid polygon repair can invent copper.
        add(graphic,kind,Polygon(points),[graphic['layer']])
    return copper, skipped


def audit(board: dict, clearance_mm: float = 0.15, tolerance_mm: float = 1e-6) -> dict:
    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError('clearance must be a finite nonnegative value')
    if not math.isfinite(tolerance_mm) or tolerance_mm < 0:
        raise ValueError('tolerance must be a finite nonnegative value')
    copper, skipped = source_copper(board)
    parent = list(range(len(copper)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(i,j): parent[find(i)] = find(j)
    bridges = {}
    for i,c in enumerate(copper):
        if c.bridge:
            if c.id in bridges: union(i,bridges[c.id])
            else: bridges[c.id] = i
    shorts, gaps = [], []
    for layer in (1,2):
        indices = [i for i,c in enumerate(copper) if c.layer==layer]
        tree = STRtree([copper[i].geometry for i in indices])
        for position,i in enumerate(indices):
            a = copper[i]
            for other in tree.query(a.geometry.buffer(max(clearance_mm,tolerance_mm))):
                if int(other) <= position: continue
                j = indices[int(other)]; b = copper[j]
                distance = a.geometry.distance(b.geometry)
                if a.net == b.net:
                    if distance <= tolerance_mm: union(i,j)
                    continue
                overlap = a.geometry.intersection(b.geometry)
                if not overlap.is_empty:
                    point=overlap.representative_point()
                    shorts.append({'type':'short_candidate','layer':layer,'nets':[a.net,b.net],'objects':[a.id,b.id],'x':round(point.x,6),'y':round(point.y,6),'overlapAreaMm2':round(overlap.area,8)})
                elif distance < clearance_mm:
                    gaps.append({'type':'clearance_candidate','layer':layer,'nets':[a.net,b.net],'objects':[a.id,b.id],'distanceMm':round(distance,6),'requiredMm':clearance_mm})
    terminals = defaultdict(lambda:defaultdict(set))
    for i,c in enumerate(copper):
        if c.terminal: terminals[c.net][find(i)].add(c.id)
    opens=[]
    for net,groups in sorted(terminals.items()):
        # Only pads are obligations. Isolated trace fragments alone do not
        # prove an unrouted terminal. Incomplete pours lower confidence.
        physical_pads = set().union(*groups.values())
        if len(groups)>1 and len(physical_pads)>1:
            opens.append({'type':'unconnected_candidate','net':net,'terminalGroups':[sorted(v) for v in groups.values()]})
    return {'experimental':True,'complete':False,'units':'mm','clearanceMm':clearance_mm,'contactToleranceMm':tolerance_mm,'coverage':dict(Counter(c.kind for c in copper)),'skipped':skipped,'shortCandidates':shorts,'clearanceCandidates':gaps,'unconnectedCandidates':opens,'summary':{'shortCandidates':len(shorts),'clearanceCandidates':len(gaps),'unconnectedNets':len(opens),'skippedObjects':len(skipped)},'limitations':['No electrical, current or firmware analysis.','Pour boundaries are not treated as filled copper; missing pours can create false unconnected candidates.','Unresolved cutouts/copper text may affect overlap results; candidates need CAD/Gerber corroboration.','Circle/ellipse/oval curves use polygonal approximation; configurable clearance is not the original board design rule.','Net labels are assumed correct; schematic-vs-PCB netlist equivalence is not checked.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path)
    p.add_argument('--gerber',type=Path)
    p.add_argument('--clearance',type=float,default=0.15)
    p.add_argument('--output',type=Path,default=Path('reports/pcb-check.json'))
    args=p.parse_args()
    import import_open_board as converter
    board=converter.parse_board(args.source or converter.DEFAULT_SOURCE,args.gerber or converter.DEFAULT_GERBER)
    result=audit(board,args.clearance)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],ensure_ascii=False))
    print('Experimental partial geometry audit only; no full-board pass/fail verdict. Report:',args.output)

if __name__=='__main__': main()
