"""Geometric source associations, never a harmlessness or electrical verdict.

Only absolute M/L/C/Z source paths are supported. Cubic paths are flattened
in millimetres with 0.001 mm control-to-chord tolerance. Closed font contours
use even/odd fill; open stroke fonts use their source stroke width.
"""
import re
from collections import Counter
from shapely.geometry import Polygon, LineString, GeometryCollection, Point
from shapely.ops import unary_union
from pcb_check import source_copper


def text_geometry(graphic, transform):
    path = graphic.get('pathRaw', '')
    tokens = re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?', path)
    if re.sub(r'[\s,]+', '', re.sub(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?', '', path)):
        raise ValueError('Invalid path token')
    origin = transform['rawOrigin']; scale = transform['scale']
    def point(x,y): return ((x-origin[0])*scale[0],(origin[1]-y)*scale[1])
    contours=[];points=[];closed=False;i=0;command=None
    def finish():
        nonlocal points,closed
        if points:contours.append((points,closed))
        points=[];closed=False
    def cubic(a,b,c,d,depth=0):
        chord=LineString([a,d])
        if max(chord.distance(Point(p)) for p in (b,c)) <= .001:
            return [d]
        if depth>=20:raise ValueError('Cubic subdivision limit')
        def mid(p,q):return ((p[0]+q[0])/2,(p[1]+q[1])/2)
        ab,bc,cd=mid(a,b),mid(b,c),mid(c,d)
        abc,bcd=mid(ab,bc),mid(bc,cd);center=mid(abc,bcd)
        return cubic(a,ab,abc,center,depth+1)+cubic(center,bcd,cd,d,depth+1)
    while i<len(tokens):
        if tokens[i].isalpha():command=tokens[i];i+=1
        if command not in ('M','L','C','Z'):raise ValueError('Unsupported source path command')
        if command=='Z':
            if not points:raise ValueError('Close without contour')
            closed=True;finish();command=None;continue
        count=6 if command=='C' else 2
        if i+count>len(tokens) or any(t.isalpha() for t in tokens[i:i+count]):raise ValueError('Missing path coordinates')
        values=list(map(float,tokens[i:i+count]));i+=count
        if command=='M':finish();points=[point(*values)];command='L'
        elif command=='L':
            if not points:raise ValueError('Line without move')
            points.append(point(*values))
        else:
            if not points:raise ValueError('Curve without move')
            points+=cubic(points[-1],point(*values[:2]),point(*values[2:4]),point(*values[4:]))
    finish()
    filled=GeometryCollection();strokes=[]
    for contour,is_closed in contours:
        if is_closed:
            poly=Polygon(contour)
            if not poly.is_valid:raise ValueError('Invalid glyph contour')
            filled=filled.symmetric_difference(poly)
        elif len(contour)>=2:
            width=graphic.get('width',0)
            if width<=0:raise ValueError('Missing stroke width')
            strokes.append(LineString(contour).buffer(width/2,quad_segs=32))
    return unary_union([filled,*strokes])


def associate_sources(board, clusters):
    """Attach per-cluster overlap evidence; does not change network analysis."""
    candidates=[];unsupported=[]
    original_pads={p['id']:p for p in board.get('pads',[]) if not p.get('net')}
    # Match copper artwork before drilling. Gerber copper flashes include the
    # future hole; source_copper normally removes it for physical annuli.
    pads=[dict(p,net='__unnamed_source__',drill=0) for p in original_pads.values()]
    pad_map={p['id']:p for p in pads}
    for copper in source_copper({'pads':pads})[0]:
        p=pad_map[copper.id]
        candidates.append((copper.layer,copper.geometry,{'kind':'unnamed-pad','id':p['id'],'ref':p.get('ref',''),'number':p.get('number',''),'plannedDrillMm':original_pads[p['id']].get('drill',0),'basis':'copper artwork footprint before drilling'}))
    transform=board.get('meta',{}).get('coordinateTransform')
    for g in board.get('graphics',[]):
        if g.get('kind')!='text' or g.get('layer') not in (1,2) or g.get('visible') is False:continue
        try:
            if not transform:raise ValueError('Missing source coordinate transform')
            geometry=text_geometry(g,transform)
            if geometry.is_empty:raise ValueError('Empty text geometry')
            candidates.append((g['layer'],geometry,{'kind':'copper-text','id':g['id'],'text':g.get('text','')}))
        except ValueError as error:unsupported.append({'id':g.get('id'),'reason':str(error)})
    source_by_layer={layer:unary_union([shape.buffer(.002) for side,shape,_ in candidates if side==layer]) for layer in (1,2)}
    for cluster in clusters:
        parts=[(p['layer'],Polygon(p['exterior'],p['holes'])) for p in cluster['geometry']]
        evidence=[];total=sum(g.area for _,g in parts)
        for layer,geometry,label in candidates:
            matching=[g for side,g in parts if side==layer and g.intersects(geometry.buffer(.002))]
            if not matching:continue
            group=unary_union(matching)
            overlap=group.intersection(geometry).area
            tolerant=group.intersection(geometry.buffer(.002)).area
            if tolerant<=1e-9:continue
            evidence.append(dict(label,layer=layer,overlapAreaMm2=round(overlap,6),coverageFraction=round(overlap/total,6),tolerantCoverageFraction=round(tolerant/total,6)))
        fraction=sum(g.intersection(source_by_layer[layer]).area for layer,g in parts)/total if total else 0
        fraction=max(0.,min(1.,fraction))
        kinds={e['kind'] for e in evidence}
        category=next(iter(kinds)) if fraction>=.98 and len(kinds)==1 else 'mixed' if fraction>=.98 and kinds else 'unresolved'
        cluster['provenance']={'category':category,'evidence':evidence,'coveredFraction':round(fraction,6),'outsideSourceAreaMm2':round(total*(1-fraction),6),'requiresReview':True}
    return {'categories':dict(Counter(c['provenance']['category'] for c in clusters)), 'unsupportedSourceGraphics':unsupported,
            'method':'Same-layer source geometry overlap; 0.002 mm quantization allowance, 98% association threshold. Pad comparison uses copper artwork before drilling; text uses source paths, not bounding boxes. Associations are not a safety verdict; all clusters remain listed.'}
