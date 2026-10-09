"""Strict bounded Gerber image parser: absolute mm, leading-zero FS, G01, C/R apertures.

Implements ordered dark/clear painting, region contours, linear draws and
flashes. Rejects unsupported arc/macro/transform/repeat commands rather than
silently producing incomplete copper. Not a general Gerber CAM engine.
"""
import re
from shapely.geometry import Point, Polygon, LineString, GeometryCollection, box
from shapely.ops import unary_union
from shapely import affinity

def parse_copper(text):
    image=GeometryCollection(); batch=[]; dark=True
    apertures={}; aperture=None; digits=None; units=False
    x=y=0.; operation=2; region=False; contour=[]; contours=[]
    counts={'regions':0,'flashes':0,'draws':0,'polarityChanges':0}
    def flush():
        nonlocal image,batch
        if batch:
            geom=unary_union(batch)
            image=image.union(geom) if dark else image.difference(geom)
            batch=[]
    def end_contour():
        nonlocal contour
        if contour:
            if len(contour)<3:raise ValueError('Region contour has fewer than 3 vertices')
            geom=Polygon(contour)
            if not geom.is_valid:raise ValueError('Invalid Gerber region contour')
            contours.append(geom);contour=[]
    def aperture_shape(px,py):
        if aperture not in apertures:raise ValueError('Undefined aperture')
        kind,values=apertures[aperture]
        if kind=='C':return Point(px,py).buffer(values[0]/2,quad_segs=64)
        w,h=values
        return box(px-w/2,py-h/2,px+w/2,py+h/2)
    for token in re.findall(r'%[^%]*%|[^%*]+\*',text):
        cmd=token.strip()
        if cmd.startswith('G04'):continue
        if cmd.startswith('%'):
            c=cmd[1:-1].rstrip('*')
            f=re.fullmatch(r'FSLAX(\d)(\d)Y(\d)(\d)',c)
            if f:
                if f.group(1,2)!=f.group(3,4):raise ValueError('Unequal X/Y format')
                digits=int(f.group(2));continue
            if c=='MOMM':units=True;continue
            if c in ('LPD','LPC'):
                if region:raise ValueError('Polarity inside unfinished region')
                flush();dark=c=='LPD';counts['polarityChanges']+=1;continue
            a=re.fullmatch(r'ADD(\d+)([CR]),(.+)',c)
            if a:
                v=[float(n) for n in a[3].split('X')]
                if len(v)!=(1 if a[2]=='C' else 2) or any(n<=0 for n in v):raise ValueError('Unsupported aperture parameters')
                apertures[int(a[1])]=(a[2],v);continue
            raise ValueError('Unsupported Gerber extended command: '+c[:50])
        c=cmd.rstrip('*')
        if c in ('G90','G75'):continue
        if c in ('M00','M02'):continue
        if c=='G36':
            if region:raise ValueError('Nested region')
            region=True;contour=[];contours=[];continue
        if c=='G37':
            if not region:raise ValueError('Region end without start')
            end_contour();geom=GeometryCollection()
            # Gerber region contours use the even/odd fill rule.
            for g in contours:geom=geom.symmetric_difference(g)
            batch.append(geom);region=False;counts['regions']+=1;continue
        select=re.fullmatch(r'(?:G54)?D(\d+)',c)
        if select and int(select[1])>=10:aperture=int(select[1]);continue
        if c=='G01':continue
        if not re.fullmatch(r'(?:G01)?(?:X[+-]?\d+)?(?:Y[+-]?\d+)?(?:D0?[123])?',c):raise ValueError('Unsupported Gerber draw command: '+c[:50])
        if digits is None or not units:raise ValueError('Missing supported mm coordinate format')
        old=(x,y)
        mx=re.search(r'X([+-]?\d+)',c);my=re.search(r'Y([+-]?\d+)',c);md=re.search(r'D0?([123])$',c)
        if mx:x=int(mx[1])/10**digits
        if my:y=int(my[1])/10**digits
        if md:operation=int(md[1])
        if not mx and not my:continue
        if region:
            if operation==2:end_contour();contour=[(x,y)]
            elif operation==1:
                if not contour:raise ValueError('Region draw without move')
                contour.append((x,y))
            else:raise ValueError('Flash inside region')
        elif operation==3:batch.append(aperture_shape(x,y));counts['flashes']+=1
        elif operation==1:
            if aperture not in apertures:raise ValueError('Draw without aperture')
            kind,values=apertures[aperture]
            if kind=='C':geom=LineString([old,(x,y)]).buffer(values[0]/2,quad_segs=64) if old!=(x,y) else aperture_shape(x,y)
            else:geom=unary_union([aperture_shape(*old),aperture_shape(x,y)]).convex_hull
            batch.append(geom);counts['draws']+=1
    if region:raise ValueError('Unterminated region')
    flush()
    if not units or digits is None:raise ValueError('Missing format/unit header')
    return image,counts

def polygons(geom):
    if geom.geom_type=='Polygon':return [geom]
    return [p for g in getattr(geom,'geoms',[]) for p in polygons(g)]
