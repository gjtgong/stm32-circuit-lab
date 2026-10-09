import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from pcb_check import audit

def track(id,net,points,layer=1,width=.2):return dict(id=id,net=net,points=points,layer=layer,width=width)
def pad(id,net,x,y,layer=1,shape='RECT',rotation=0,plated=None):return dict(id=id,net=net,x=x,y=y,layer=layer,width=.5,height=.5,shape=shape,rotation=rotation,drill=.15 if layer==11 else 0,plated=plated)
def board(tracks=(),pads=(),vias=(),graphics=()):return dict(tracks=list(tracks),pads=list(pads),vias=list(vias),graphics=list(graphics))
class GeometryTests(unittest.TestCase):
 def test_normal_connected_net(self):
  r=audit(board([track('t','A',[(0,0),(2,0)])],[pad('a','A',0,0),pad('b','A',2,0)]))
  self.assertEqual(r['summary']['shortCandidates'],0);self.assertEqual(r['summary']['unconnectedNets'],0)
 def test_same_layer_crossing_is_short(self):
  r=audit(board([track('a','A',[(0,0),(2,0)]),track('b','B',[(1,-1),(1,1)])]))
  self.assertEqual(len(r['shortCandidates']),1);self.assertAlmostEqual(r['shortCandidates'][0]['x'],1,delta=.11)
 def test_different_layer_crossing_is_not_short(self):
  r=audit(board([track('a','A',[(0,0),(2,0)]),track('b','B',[(1,-1),(1,1)],2)]))
  self.assertEqual(r['summary']['shortCandidates'],0)
 def test_broken_track_separates_terminals(self):
  r=audit(board([track('a','A',[(0,0),(.7,0)]),track('b','A',[(1.3,0),(2,0)])],[pad('p1','A',0,0),pad('p2','A',2,0)]))
  self.assertEqual(len(r['unconnectedCandidates']),1);self.assertEqual(len(r['unconnectedCandidates'][0]['terminalGroups']),2)
 def test_layers_need_plated_bridge(self):
  tracks=[track('a','A',[(0,0),(1,0)]),track('b','A',[(1,0),(2,0)],2)]
  pads=[pad('p1','A',0,0),pad('p2','A',2,0,2)]
  self.assertEqual(audit(board(tracks,pads))['summary']['unconnectedNets'],1)
  v=dict(id='v',net='A',x=1,y=0,diameter=.6,drill=.2)
  self.assertEqual(audit(board(tracks,pads,[v]))['summary']['unconnectedNets'],0)
 def test_unplated_hole_does_not_bridge(self):
  tracks=[track('a','A',[(0,0),(1,0)]),track('b','A',[(1,0),(2,0)],2)]
  pads=[pad('p1','A',0,0),pad('p2','A',2,0,2),pad('h','A',1,0,11,plated='N')]
  self.assertEqual(audit(board(tracks,pads))['summary']['unconnectedNets'],1)
  pads[-1]['plated']='Y'
  self.assertEqual(audit(board(tracks,pads))['summary']['unconnectedNets'],0)
 def test_parallel_clearance_not_short(self):
  r=audit(board([track('a','A',[(0,0),(2,0)]),track('b','B',[(0,.3),(2,.3)])]),.15)
  self.assertEqual(r['summary']['shortCandidates'],0);self.assertEqual(r['summary']['clearanceCandidates'],1)
 def test_pour_boundary_cannot_fake_connection(self):
  g=dict(id='pour',kind='copper-area',layer=1,net='A',pointsMM=[[-1,-1],[3,-1],[3,1],[-1,1]])
  r=audit(board(pads=[pad('a','A',0,0),pad('b','A',2,0)],graphics=[g]))
  self.assertEqual(r['summary']['unconnectedNets'],1);self.assertEqual(len(r['skipped']),1);self.assertFalse(r['complete'])
 def test_trace_inside_drill_is_not_pad_contact(self):
  p=pad('h','A',0,0,11,plated='Y');p['drill']=.4
  r=audit(board([track('tiny','B',[(-.02,0),(.02,0)],width=.02)],[p]))
  self.assertEqual(r['summary']['shortCandidates'],0)
 def test_invalid_threshold_rejected(self):
  for x in [-1,float('nan'),float('inf')]:
   with self.assertRaises(ValueError):audit(board(),x)
class ActualBoardFaultTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import import_open_board as converter
  if not converter.DEFAULT_SOURCE.exists() or not converter.DEFAULT_GERBER.exists():
   raise unittest.SkipTest('Acquire third-party PCB locally with tools/fetch_open_board.py')
  cls.board=converter.parse_board(converter.DEFAULT_SOURCE,converter.DEFAULT_GERBER)
  cls.baseline=audit(cls.board)
 def test_adjacent_mcu_pin_bridge_is_detected(self):
  import copy
  bad=copy.deepcopy(self.board)
  pads=sorted([p for p in bad['pads'] if p.get('ref')=='U2' and p.get('net')],key=lambda p:int(p['number']))
  a,b=pads[:2]
  self.assertNotEqual(a['net'],b['net'])
  bad['tracks'].append(track('TEST-injected-bridge',a['net'],[(a['x'],a['y']),(b['x'],b['y'])]))
  result=audit(bad)
  self.assertTrue(any('TEST-injected-bridge' in c['objects'] and b['net'] in c['nets'] for c in result['shortCandidates']))
  self.assertFalse(any(t['id']=='TEST-injected-bridge' for t in self.board['tracks']))
 def test_removing_actual_pe15_tracks_creates_new_open_candidate(self):
  import copy
  bad=copy.deepcopy(self.board)
  self.assertFalse(any(c['net']=='PE15' for c in self.baseline['unconnectedCandidates']))
  self.assertTrue(any(t['net']=='PE15' for t in bad['tracks']))
  bad['tracks']=[t for t in bad['tracks'] if t.get('net')!='PE15']
  result=audit(bad)
  self.assertTrue(any(c['net']=='PE15' for c in result['unconnectedCandidates']))
  self.assertTrue(any(t['net']=='PE15' for t in self.board['tracks']))

if __name__=='__main__':unittest.main()
