"""Audit authoritative Gerber island connectivity, seeded by known PCB pads/vias."""
from collections import defaultdict
from shapely.strtree import STRtree
from pcb_check import source_copper
from gerber_copper import polygons

def audit_gerber(board, layers):
    source,_=source_copper(board)
    seeds=[c for c in source if c.kind in ('pad','via')]
    islands=[]; per_layer={}; trees={}
    for layer,image in sorted(layers.items()):
        ids=[]
        for g in polygons(image):ids.append(len(islands));islands.append({'layer':layer,'geometry':g,'nets':set(),'pads':defaultdict(set)})
        per_layer[layer]=ids;trees[layer]=STRtree([islands[i]['geometry'] for i in ids])
    parent=list(range(len(islands)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(i,j):parent[find(i)]=find(j)
    hits=defaultdict(dict); bridges=set(); missing=[]; partial=[]
    for seed in seeds:
        if seed.layer not in trees:continue
        matches=[];covered=0
        for pos in trees[seed.layer].query(seed.geometry):
            idx=per_layer[seed.layer][int(pos)]
            area=seed.geometry.intersection(islands[idx]['geometry']).area
            covered+=area
            # Robust against 3-decimal Gerber coordinate quantization: tiny
            # sliver intersections alone must not assign a whole copper island.
            if area/seed.geometry.area>=.25:
                matches.append(idx);islands[idx]['nets'].add(seed.net)
                if seed.terminal:islands[idx]['pads'][seed.net].add(seed.id)
        hits[seed.id][seed.layer]=matches
        if seed.bridge:bridges.add(seed.id)
        if not matches:missing.append({'id':seed.id,'layer':seed.layer,'net':seed.net})
        if covered/seed.geometry.area<.90:partial.append({'id':seed.id,'layer':seed.layer,'coveredFraction':round(covered/seed.geometry.area,5)})
    ambiguous=[]
    for id in sorted(bridges):
        bylayer=hits[id]
        if len(bylayer)==2 and all(len(v)==1 for v in bylayer.values()):
            a,b=[v[0] for v in bylayer.values()];union(a,b)
        elif any(len(v)>1 for v in bylayer.values()):ambiguous.append(id)
    clusters=defaultdict(list)
    for i in range(len(islands)):clusters[find(i)].append(i)
    conflicts=[];netgroups=defaultdict(list);unassigned=[]
    for indices in clusters.values():
        nets=set().union(*(islands[i]['nets'] for i in indices))
        pads=defaultdict(set)
        for i in indices:
            for net,ids in islands[i]['pads'].items():pads[net].update(ids)
        if len(nets)>1:
            g=islands[indices[0]]['geometry'];pt=g.representative_point()
            conflicts.append({'nets':sorted(nets),'layers':sorted({islands[i]['layer'] for i in indices}),'islands':indices,'pads':{n:sorted(v) for n,v in pads.items()},'x':round(pt.x,6),'y':round(pt.y,6)})
            # Do not give a net-conflicted cluster a guessed single-net label.
            continue
        if not nets:
            unassigned.append({'id':f'copper-{indices[0]}','islands':indices,
                'areaMm2':round(sum(islands[i]['geometry'].area for i in indices),6),
                'geometry':[{'layer':islands[i]['layer'],
                    'exterior':[[round(x,6),round(y,6)] for x,y in islands[i]['geometry'].exterior.coords],
                    'holes':[[[round(x,6),round(y,6)] for x,y in ring.coords] for ring in islands[i]['geometry'].interiors]}
                    for i in indices]})
            continue
        net=next(iter(nets))
        if pads[net]:netgroups[net].append(sorted(pads[net]))
    from copper_provenance import associate_sources
    provenance = associate_sources(board, unassigned)
    opens=[{'net':n,'terminalGroups':groups} for n,groups in sorted(netgroups.items()) if len(groups)>1 and len({p for g in groups for p in g})>1]
    return {'experimental':True,'complete':False,'basis':'Ordered Gerber copper image; network labels inferred from >=25% overlap with known PCB pad/via seed geometry','summary':{'netConflictClusters':len(conflicts),'unconnectedNets':len(opens),'unassignedClusters':len(unassigned),'missingSeeds':len(missing),'partialSeeds':len(partial),'ambiguousBridges':len(ambiguous)},'provenanceSummary':provenance,'netConflicts':conflicts,'unconnectedCandidates':opens,'unassignedClusters':unassigned,'missingSeeds':missing,'partialSeeds':partial,'ambiguousBridges':ambiguous,'islandCounts':{layer:len(ids) for layer,ids in per_layer.items()},'limitations':['No electrical analysis or full-board manufacturing verdict.','Network names are inferred from PCB pad/via labels; Gerber carries no net identity here.','25% seed overlap threshold tolerates quantization but partial/missing seeds require review.','No general Gerber arc/macro/transform/repeat support; unsupported commands are rejected.','No spacing/manufacturing-rule audit in this Gerber connectivity check.']}


def main():
    import argparse
    import json
    from pathlib import Path
    import import_open_board as converter
    from gerber_copper import parse_copper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=converter.DEFAULT_SOURCE)
    parser.add_argument('--gerber-dir', type=Path, default=converter.DEFAULT_GERBER.parent)
    parser.add_argument('--output', type=Path, default=Path('reports/gerber-check.json'))
    args = parser.parse_args()
    board = converter.parse_board(args.source, args.gerber_dir / converter.DEFAULT_GERBER.name)
    images, coverage = {}, {}
    for layer, filename in ((1, 'Gerber_TopLayer.GTL'), (2, 'Gerber_BottomLayer.GBL')):
        images[layer], counts = parse_copper((args.gerber_dir / filename).read_text())
        coverage[filename] = dict(counts, copperAreaMm2=round(images[layer].area, 6))
    result = audit_gerber(board, images)
    result['gerberCoverage'] = coverage
    import hashlib
    import os
    base = Path(__file__).resolve().parents[1]
    inputs = [args.source, args.gerber_dir / 'Gerber_TopLayer.GTL', args.gerber_dir / 'Gerber_BottomLayer.GBL']
    result['inputHashes'] = {os.path.relpath(path.resolve(), base):hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    result['boardSizeMm'] = {'width':board['meta']['widthMm'], 'height':board['meta']['heightMm']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
    print('Experimental connectivity check; unassigned copper requires review. Report:', args.output)

if __name__ == '__main__':
    main()
