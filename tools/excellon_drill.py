"""Bounded EasyEDA metric absolute Excellon hits and inline G85 slots.

Reject other dialects/commands rather than silently invent drill geometry.
Plating is supplied by the caller's PTH/NPTH file identity, never inferred.
"""
import re
from shapely.geometry import Point, LineString
from shapely.ops import unary_union


def parse_drills(text):
    tools, holes = {}, []
    state = 'start'
    metric = absolute = ended = False
    selected = None
    coordinate = r'X([+-]?\d{1,6})Y([+-]?\d{1,6})'
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(';'):
            continue
        if ended:
            raise ValueError('Data after Excellon end')
        if state == 'start' and line == 'M48':
            state = 'header'; continue
        if state == 'header':
            if line == 'METRIC,LZ,000.000' and not metric:
                metric = True; continue
            tool = re.fullmatch(r'T(\d+)C(\d+(?:\.\d+)?)', line)
            if tool and metric:
                number, diameter = int(tool[1]), float(tool[2])
                if number in tools or diameter <= 0:
                    raise ValueError('Invalid drill tool')
                tools[number] = diameter; continue
            if line == '%' and metric and tools:
                state = 'body'; continue
            raise ValueError(f'Unsupported Excellon header: {line}')
        if state != 'body':
            raise ValueError('Missing Excellon header')
        if line == 'G05': continue
        if line == 'G90': absolute = True; continue
        if line == 'M30': ended = True; continue
        tool = re.fullmatch(r'T(\d+)', line)
        if tool:
            selected = int(tool[1])
            if selected not in tools: raise ValueError('Unknown drill tool')
            continue
        hit = re.fullmatch(coordinate + r'(?:G85' + coordinate + r')?', line)
        if hit and absolute and selected is not None:
            start = (int(hit[1])/1000, int(hit[2])/1000)
            points = [start]
            if hit[3] is not None:
                points.append((int(hit[3])/1000, int(hit[4])/1000))
                if points[0] == points[1]: raise ValueError('Zero-length slot')
            path = LineString(points) if len(points) == 2 else Point(start)
            holes.append({'tool':selected, 'diameter':tools[selected],
                          'points':points, 'slot':len(points)==2,
                          'geometry':path.buffer(tools[selected]/2, quad_segs=64)})
            continue
        raise ValueError(f'Unsupported Excellon body: {line}')
    if not ended or not absolute or not holes:
        raise ValueError('Incomplete Excellon drill file')
    return holes


def remove_drills(images, holes):
    """Subtract both plated and unplated material removal; no layer bridging."""
    cuts = unary_union([hole['geometry'] for hole in holes])
    return {layer:image.difference(cuts) for layer,image in images.items()}
