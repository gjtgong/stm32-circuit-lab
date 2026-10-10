import sys, unittest
from pathlib import Path
from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from manufacturing_check import audit_manufacturing
from excellon_drill import remove_drills

def hole(x=0,y=0,r=.3,plated=True,slot=False):
 g=LineString([(x,y-.6),(x,y+.6)]) if slot else Point(x,y)
 return dict(geometry=g.buffer(r,quad_segs=64),plated=plated,slot=slot)
def pad(id,net,x,y):return dict(id=id,net=net,x=x,y=y,width=.1,height=.1,shape='RECT',layer=1,drill=0)
def check(artwork,holes=(),board=None,**kwargs):
 images={1:artwork,2:artwork}
 return audit_manufacturing(board or {},images,remove_drills(images,holes),holes,**kwargs)
class ManufacturingTests(unittest.TestCase):
 def test_good_annulus_on_both_layers(self):
  self.assertEqual(check(Point(0,0).buffer(.5,quad_segs=64),[hole()])['summary']['annularRingCandidates'],0)
 def test_thin_annulus_detected_on_both_layers(self):
  self.assertEqual(check(Point(0,0).buffer(.35,quad_segs=64),[hole()])['summary']['annularRingCandidates'],2)
 def test_missing_sector_detected_despite_mostly_good_ring(self):
  copper=Point(0,0).buffer(.5,quad_segs=64).difference(box(.32,-.05,.6,.05))
  self.assertEqual(check(copper,[hole()])['summary']['annularRingCandidates'],2)
 def test_slot_cap_annulus_is_checked(self):
  h=hole(slot=True);copper=h['geometry'].buffer(.15)
  self.assertEqual(check(copper,[h])['summary']['annularRingCandidates'],0)
  self.assertEqual(check(copper.difference(box(-.1,.92,.1,1.2)),[h])['summary']['annularRingCandidates'],2)
 def test_npth_near_copper_detected_and_clear_hole_not_ring_checked(self):
  h=hole(plated=False)
  result=check(box(.4,-.5,1,.5),[h])
  self.assertEqual(result['summary']['npthCopperCandidates'],2)
  self.assertEqual(result['summary']['annularRingCandidates'],0)
  self.assertEqual(check(box(.6,-.5,1,.5),[h])['summary']['npthCopperCandidates'],0)
 def test_hole_gap_uses_bore_edges_including_slot(self):
  self.assertEqual(check(box(-2,-2,2,2),[hole(),hole(x=.7)])['summary']['holeClearanceCandidates'],1)
  self.assertEqual(check(box(-2,-2,2,2),[hole(),hole(x=1)])['summary']['holeClearanceCandidates'],0)
 def test_different_known_nets_detected_same_net_exempt_unknown_kept(self):
  copper=unary_union([box(0,0,1,1),box(1.1,0,2.1,1)])
  b={'pads':[pad('a','A',.5,.5),pad('b','B',1.6,.5)]}
  self.assertEqual(check(copper,board=b)['summary']['knownNetCopperClearanceCandidates'],1)
  b['pads'][1]['net']='A'
  self.assertEqual(check(copper,board=b)['summary']['knownNetCopperClearanceCandidates'],0)
  self.assertEqual(check(copper)['summary']['unresolvedCopperClearanceCandidates'],2)
 def test_threshold_boundary_tolerates_declared_quantization(self):
  copper=unary_union([box(0,0,1,1),box(1.149,0,2.149,1)])
  self.assertEqual(check(copper)['summary']['unresolvedCopperClearanceCandidates'],0)
  self.assertEqual(check(copper,quantization_tolerance=0)['summary']['unresolvedCopperClearanceCandidates'],2)
 def test_bottom_island_provenance_uses_global_offset_and_keeps_candidates(self):
  from manufacturing_check import attach_copper_provenance
  m={'summary':{},'unresolvedCopperClearanceCandidates':[{'layer':2,'islands':[0,1]}]}
  c={'islandCounts':{'1':3,'2':2},'unassignedClusters':[{'islands':[i],'provenance':{'category':'copper-text','requiresReview':True}} for i in [3,4]]}
  attach_copper_provenance(m,c)
  self.assertEqual(m['summary']['copperTextSpacingCandidates'],1)
  self.assertEqual(len(m['unresolvedCopperClearanceCandidates']),1)
  self.assertEqual(m['unresolvedCopperClearanceCandidates'][0]['sourceEvidence'][1]['copperId'],'copper-4')
 def test_missing_plating_or_layer_and_invalid_threshold_fail_closed(self):
  for kwargs in [dict(annular_ring=-1),dict(copper_clearance=float('nan'))]:
   with self.assertRaises(ValueError):check(box(-1,-1,1,1),**kwargs)
  h=hole();del h['plated']
  with self.assertRaises(ValueError):check(box(-1,-1,1,1),[h])
  with self.assertRaises(ValueError):audit_manufacturing({}, {1:box(0,0,1,1)}, {1:box(0,0,1,1)}, [])

class ActualManufacturingFaultTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import import_open_board as converter
  from gerber_copper import parse_copper
  from excellon_drill import parse_drills
  if not converter.DEFAULT_SOURCE.exists(): raise unittest.SkipTest('Acquire board locally')
  cls.board=converter.parse_board();cls.artwork={}
  for layer,name in [(1,'Gerber_TopLayer.GTL'),(2,'Gerber_BottomLayer.GBL')]:
   cls.artwork[layer]=parse_copper((converter.DEFAULT_GERBER.parent/name).read_text())[0]
  cls.holes=[]
  for plated,name in [(True,'Gerber_Drill_PTH.DRL'),(False,'Gerber_Drill_NPTH.DRL')]:
   hs=parse_drills((converter.DEFAULT_GERBER.parent/name).read_text())
   for h in hs:h['plated']=plated
   cls.holes.extend(hs)
  cls.baseline=audit_manufacturing(cls.board,cls.artwork,remove_drills(cls.artwork,cls.holes),cls.holes)
 def test_actual_via_ring_sector_removal_detected(self):
  h=self.holes[0];x,y=h['points'][0];r=h['diameter']/2
  bad=dict(self.artwork)
  bad[1]=bad[1].difference(box(x+r+.02,y-.025,x+r+.15,y+.025))
  result=audit_manufacturing(self.board,bad,remove_drills(bad,self.holes),self.holes)
  self.assertEqual(self.baseline['summary']['annularRingCandidates'],0)
  self.assertTrue(any(item['drill']==0 and item['layer']==1 for item in result['annularRingCandidates']))
  self.assertEqual(audit_manufacturing(self.board,self.artwork,remove_drills(self.artwork,self.holes),self.holes)['summary']['annularRingCandidates'],0)
 def test_actual_npth_clearance_intrusion_detected(self):
  i=next(i for i,h in enumerate(self.holes) if not h['plated'])
  h=self.holes[i];x,y=h['points'][0];r=h['diameter']/2
  bad=dict(self.artwork)
  bad[1]=bad[1].union(box(x+r+.04,y-.025,x+r+.08,y+.025))
  result=audit_manufacturing(self.board,bad,remove_drills(bad,self.holes),self.holes)
  self.assertEqual(self.baseline['summary']['npthCopperCandidates'],0)
  self.assertTrue(any(item['drill']==i and item['layer']==1 for item in result['npthCopperCandidates']))

if __name__=='__main__':unittest.main()
