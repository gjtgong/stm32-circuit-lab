"""Nominal two-layer geometry candidates, with explicit experimental thresholds.

No manufacturer rule or whole-board electrical/manufacturing pass is inferred.
Unknown-net copper remains separate review evidence rather than a proven fault.
"""
import math
from collections import defaultdict
from shapely.strtree import STRtree
from shapely.ops import nearest_points
from pcb_check import source_copper
from gerber_copper import polygons


def attach_copper_provenance(manufacturing, connectivity):
    """Link local layer island indices to the same Gerber audit's source evidence."""
    lookup = {i:cluster for cluster in connectivity['unassignedClusters'] for i in cluster['islands']}
    offset, offsets = 0, {}
    for layer,count in sorted((int(layer),count) for layer,count in connectivity['islandCounts'].items()):
        offsets[layer] = offset
        offset += count
    text_pairs = 0
    for item in manufacturing['unresolvedCopperClearanceCandidates']:
        evidence = []
        for local_index in item['islands']:
            index = offsets[item['layer']] + local_index
            cluster = lookup.get(index)
            evidence.append({'copperId':f'copper-{index}',
                'provenance':cluster.get('provenance') if cluster else None})
        item['sourceEvidence'] = evidence
        if all(e['provenance'] and e['provenance']['category'] == 'copper-text' for e in evidence):
            text_pairs += 1
    manufacturing['summary']['copperTextSpacingCandidates'] = text_pairs


def audit_manufacturing(board, artwork, drilled, drills, *, copper_clearance=.15,
                        annular_ring=.10, npth_clearance=.15, hole_clearance=.25,
                        quantization_tolerance=.002):
    rules = dict(copperClearanceMm=copper_clearance, annularRingMm=annular_ring,
                 npthCopperClearanceMm=npth_clearance, holeClearanceMm=hole_clearance,
                 quantizationToleranceMm=quantization_tolerance)
    if any(not math.isfinite(x) or x < 0 for x in rules.values()):
        raise ValueError('Thresholds must be finite and nonnegative')
    if set(artwork) != set(drilled) or set(artwork) != {1,2}:
        raise ValueError('Both copper layers are required')
    if any(h.get('plated') not in (True,False) for h in drills):
        raise ValueError('Every drill must explicitly identify PTH or NPTH')
    tol = quantization_tolerance
    # Whole-board artwork buffers are expensive; compute each layer once,
    # rather than once per plated hole.
    expanded_artwork = {layer:image.buffer(tol,quad_segs=64) for layer,image in artwork.items()}
    rings, npth, hole_gaps, gaps, unknown = [], [], [], [], []
    def location(a, b):
        p,q = nearest_points(a,b)
        return {'x':round((p.x+q.x)/2,6),'y':round((p.y+q.y)/2,6)}
    for index,hole in enumerate(drills):
        geometry = hole['geometry']
        if hole['plated']:
            shell = geometry.buffer(annular_ring,quad_segs=64).difference(geometry)
            for layer,image in artwork.items():
                missing = shell.difference(expanded_artwork[layer])
                if missing.area > 1e-8:
                    point = missing.representative_point()
                    rings.append({'drill':index,'layer':layer,'slot':hole['slot'],
                                  'missingRingAreaMm2':round(missing.area,8),
                                  'x':round(point.x,6),'y':round(point.y,6)})
        else:
            protected = geometry.buffer(max(0,npth_clearance-tol),quad_segs=64)
            for layer,image in artwork.items():
                overlap = protected.intersection(image)
                if overlap.area > 1e-8:
                    point = overlap.representative_point()
                    npth.append({'drill':index,'layer':layer,
                                 'copperDistanceMm':round(geometry.distance(image),6),
                                 'x':round(point.x,6),'y':round(point.y,6)})
    geometries = [hole['geometry'] for hole in drills]
    tree = STRtree(geometries)
    for i,a in enumerate(geometries):
        for pos in tree.query(a.buffer(hole_clearance)):
            j=int(pos)
            if j <= i: continue
            distance = a.distance(geometries[j])
            if distance+tol < hole_clearance:
                hole_gaps.append(dict(drills=[i,j],distanceMm=round(distance,6),**location(a,geometries[j])))
    source,_ = source_copper(board)
    seeds = defaultdict(list)
    for seed in source:
        if seed.kind in ('pad','via'): seeds[seed.layer].append(seed)
    for layer,image in sorted(drilled.items()):
        islands = list(polygons(image))
        tree = STRtree(islands)
        labels = [set() for _ in islands]
        for seed in seeds[layer]:
            for pos in tree.query(seed.geometry):
                i=int(pos)
                if seed.geometry.intersection(islands[i]).area/seed.geometry.area >= .25:
                    labels[i].add(seed.net)
        for i,a in enumerate(islands):
            for pos in tree.query(a.buffer(copper_clearance)):
                j=int(pos)
                if j <= i: continue
                distance = a.distance(islands[j])
                if distance+tol >= copper_clearance: continue
                # Same uniquely identified net is exempt from copper clearance.
                if len(labels[i]) == len(labels[j]) == 1 and labels[i] == labels[j]: continue
                item = dict(layer=layer,islands=[i,j],distanceMm=round(distance,6),
                            nets=[sorted(labels[i]),sorted(labels[j])],**location(a,islands[j]))
                if len(labels[i]) == len(labels[j]) == 1: gaps.append(item)
                else: unknown.append(item)
    summary = dict(annularRingCandidates=len(rings),npthCopperCandidates=len(npth),
                   holeClearanceCandidates=len(hole_gaps),
                   knownNetCopperClearanceCandidates=len(gaps),
                   unresolvedCopperClearanceCandidates=len(unknown))
    return dict(experimental=True,complete=False,thresholdOrigin='Explicit test thresholds; not confirmed manufacturer rules',
                drills=[{key:hole.get(key) for key in ('sourceFile','sourceHit','tool','diameter','points','plated','slot')} for hole in drills],
                thresholds=rules,summary=summary,annularRingCandidates=rings,
                npthCopperCandidates=npth,holeClearanceCandidates=hole_gaps,
                knownNetCopperClearanceCandidates=gaps,unresolvedCopperClearanceCandidates=unknown,
                limitations=['Nominal polygons only; no plating thickness, drill registration, process tolerances or thermal/current analysis.',
                             'Annular ring compares the requested outward drill offset with copper artwork on both layers.',
                             'Copper spacing uses distinct islands and uniquely matched PCB pad/via net labels. Same-island shorts are handled by connectivity audit.',
                             'Unknown or conflicted net spacing requires review; copper glyph gaps are not automatically electrical faults.',
                             'No trace-width, board-edge, soldermask, paste, stackup or full manufacturing rule coverage.'])
