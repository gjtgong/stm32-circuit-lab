import sys,unittest
from pathlib import Path
from shapely.geometry import box,LineString
from shapely.ops import unary_union
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from gerber_copper import parse_copper
from gerber_check import audit_gerber
HEADER='%FSLAX33Y33*%\n%MOMM*%\n'
def region(x0,y0,x1,y1):
 return f'G36*\nX{x0}Y{y0}D02*\nX{x1}Y{y0}D01*\nX{x1}Y{y1}D01*\nX{x0}Y{y1}D01*\nG37*\n'
def pad(id,net,x,y,layer=1):return dict(id=id,net=net,x=x,y=y,layer=layer,width=.5,height=.5,shape='RECT',drill=0,rotation=0)
class GerberParserTests(unittest.TestCase):
 def test_dark_clear_dark_order(self):
  g,c=parse_copper(HEADER+'%LPD*%'+region(0,0,10000,10000)+'%LPC*%'+region(2000,2000,8000,8000)+'%LPD*%'+region(3000,3000,7000,7000))
  self.assertAlmostEqual(g.area,80);self.assertEqual(c['regions'],3)
 def test_multicontour_hole_even_odd(self):
  s=HEADER+'G36*X0Y0D02*X10000Y0D01*X10000Y10000D01*X0Y10000D01*X2000Y2000D02*X8000Y2000D01*X8000Y8000D01*X2000Y8000D01*G37*'
  self.assertAlmostEqual(parse_copper(s)[0].area,64)
 def test_clear_flash_erases_copper(self):
  s=HEADER+'%ADD10R,2X2*%'+region(0,0,10000,10000)+'%LPC*%D10*X5000Y5000D03*'
  self.assertAlmostEqual(parse_copper(s)[0].area,96)
 def test_modal_axis_and_linear_draw(self):
  g,c=parse_copper(HEADER+'%ADD10C,0.2*%D10*X0Y0D02*X1000D01*Y1000D01*')
  self.assertEqual(c['draws'],2);self.assertGreater(g.area,.4);self.assertEqual(g.bounds,(-.1,-.1,1.1,1.1))
 def test_rectangle_draw_sweeps_aperture(self):
  g,_=parse_copper(HEADER+'%ADD10R,1X2*%D10*X0Y0D02*X1000Y0D01*')
  self.assertAlmostEqual(g.area,4)
 def test_unsupported_features_fail_closed(self):
  for command in ['%MOIN*%','%SRX2Y2I1J1*%','G02X1000Y1000I500J0D01*','%AMfoo*1,1,1,0,0*%','%LMX*%']:
   with self.assertRaises(ValueError):parse_copper(HEADER+command)
 def test_invalid_region_rejected(self):
  with self.assertRaises(ValueError):parse_copper(HEADER+'G36*X0Y0D02*X1000Y1000D01*X1000Y0D01*X0Y1000D01*G37*')
class GerberConnectivityTests(unittest.TestCase):
 def test_filled_plane_connects_same_net_pads(self):
  b={'pads':[pad('p1','GND',0,0),pad('p2','GND',2,0)]}
  self.assertEqual(audit_gerber(b,{1:box(-1,-1,3,1)})['summary']['unconnectedNets'],0)
 def test_gap_in_plane_separates_same_net_pads(self):
  b={'pads':[pad('p1','A',0,0),pad('p2','A',2,0)]}
  g=unary_union([box(-.5,-.5,.5,.5),box(1.5,-.5,2.5,.5)])
  self.assertEqual(audit_gerber(b,{1:g})['summary']['unconnectedNets'],1)
 def test_same_island_with_two_net_seeds_is_conflict(self):
  b={'pads':[pad('p1','A',0,0),pad('p2','B',2,0)]}
  r=audit_gerber(b,{1:box(-1,-1,3,1)})
  self.assertEqual(r['summary']['netConflictClusters'],1);self.assertEqual(r['netConflicts'][0]['nets'],['A','B'])
 def test_different_layers_are_not_merged_without_via(self):
  b={'pads':[pad('p1','A',0,0),pad('p2','A',0,0,2)]}
  r=audit_gerber(b,{1:box(-1,-1,1,1),2:box(-1,-1,1,1)})
  self.assertEqual(r['summary']['netConflictClusters'],0);self.assertEqual(r['summary']['unconnectedNets'],1)
 def test_via_connects_actual_layer_islands(self):
  b={'pads':[pad('p1','A',0,0),pad('p2','A',2,0,2)],'vias':[dict(id='v',net='A',x=1,y=0,diameter=.6,drill=.2)]}
  r=audit_gerber(b,{1:box(-.5,-.5,1.5,.5),2:box(.5,-.5,2.5,.5)})
  self.assertEqual(r['summary']['unconnectedNets'],0)
 def test_unassigned_export_preserves_hole_and_layer(self):
  from shapely.geometry import Polygon
  g=Polygon([(0,0),(3,0),(3,3),(0,3)],holes=[[(1,1),(2,1),(2,2),(1,2)]])
  r=audit_gerber({'pads':[]},{2:g})
  cluster=r['unassignedClusters'][0]; exported=cluster['geometry'][0]
  self.assertEqual(exported['layer'],2)
  self.assertAlmostEqual(Polygon(exported['exterior'],exported['holes']).area,cluster['areaMm2'])
  self.assertEqual(len(exported['holes']),1)
 def test_missing_seed_is_reported(self):
  r=audit_gerber({'pads':[pad('p','A',10,10)]},{1:box(0,0,1,1)})
  self.assertEqual(r['summary']['missingSeeds'],1);self.assertEqual(r['summary']['unassignedClusters'],1)
class ActualGerberTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import import_open_board as m
  if not m.DEFAULT_SOURCE.exists() or not (m.DEFAULT_GERBER.parent/'Gerber_TopLayer.GTL').exists():raise unittest.SkipTest('Acquire source locally first')
  cls.board=m.parse_board(m.DEFAULT_SOURCE,m.DEFAULT_GERBER)
  cls.images={};cls.counts={}
  for layer,name in [(1,'Gerber_TopLayer.GTL'),(2,'Gerber_BottomLayer.GBL')]:cls.images[layer],cls.counts[layer]=parse_copper((m.DEFAULT_GERBER.parent/name).read_text())
 def test_actual_ground_connectivity_resolved(self):
  r=audit_gerber(self.board,self.images)
  self.assertFalse(any(c['net']=='GND' for c in r['unconnectedCandidates']))
  self.assertEqual(r['summary']['missingSeeds'],0);self.assertEqual(r['summary']['partialSeeds'],0)
  self.assertEqual(self.counts[1]['regions'],447);self.assertEqual(self.counts[2]['regions'],522)
 def test_injected_gerber_bridge_detected(self):
  pads=sorted([p for p in self.board['pads'] if p.get('ref')=='U2' and p.get('net')],key=lambda p:int(p['number']))
  a,b=pads[:2];images=dict(self.images)
  images[1]=images[1].union(LineString([(a['x'],a['y']),(b['x'],b['y'])]).buffer(.10))
  r=audit_gerber(self.board,images)
  self.assertTrue(any(a['net'] in c['nets'] and b['net'] in c['nets'] for c in r['netConflicts']))
 def test_removed_gerber_route_reports_mismatch_or_open(self):
  images=dict(self.images)
  for layer in images:
   cut=unary_union([LineString(t['points']).buffer(t['width']/2+.01) for t in self.board['tracks'] if t.get('net')=='PE15' and t['layer']==layer])
   images[layer]=images[layer].difference(cut)
  r=audit_gerber(self.board,images)
  self.assertTrue(any(c['net']=='PE15' for c in r['unconnectedCandidates']) or any(c['net']=='PE15' for c in r['missingSeeds']))
if __name__=='__main__':unittest.main()
