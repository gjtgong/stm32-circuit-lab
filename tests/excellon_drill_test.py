import sys, unittest
from pathlib import Path
from shapely.geometry import box
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from excellon_drill import parse_drills, remove_drills
from gerber_check import audit_gerber
HEADER='M48\nMETRIC,LZ,000.000\nT01C0.600\n%\nG05\nG90\nT01\n'
class DrillTests(unittest.TestCase):
 def test_slot_has_round_caps_and_declared_units(self):
  h=parse_drills(HEADER+'X+039400Y+042699G85X+039400Y+041499\nM30')[0]
  self.assertTrue(h['slot'])
  for actual, expected in zip(h['geometry'].bounds,(39.1,41.199,39.7,42.999)): self.assertAlmostEqual(actual,expected)
 def test_drill_cut_creates_real_open_in_copper(self):
  b={'pads':[dict(id=str(x),net='A',x=x,y=0,layer=1,width=.2,height=.2,shape='RECT',drill=0) for x in (0,2)]}
  image={1:box(-.2,-.1,2.2,.1)}
  self.assertEqual(audit_gerber(b,image)['summary']['unconnectedNets'],0)
  holes=parse_drills(HEADER+'X001000Y000000\nM30')
  self.assertEqual(audit_gerber(b,remove_drills(image,holes))['summary']['unconnectedNets'],1)
 def test_unsupported_or_incomplete_commands_rejected(self):
  for text in [HEADER+'G91\nM30',HEADER+'G00X001000Y001000\nM30',HEADER+'T02\nM30',HEADER+'X000000Y000000',HEADER.replace('METRIC,LZ,000.000','INCH,LZ,00.0000')+'M30',HEADER+'X0Y0\nM30\nX1Y1']:
   with self.assertRaises(ValueError): parse_drills(text)
 def test_actual_slots_match_source_geometry_without_second_rotation(self):
  import import_open_board as m
  from shapely.geometry import LineString,Point
  if not m.DEFAULT_SOURCE.exists(): self.skipTest('Acquire board source locally')
  b=m.parse_board()
  actual=parse_drills((m.DEFAULT_GERBER.parent/'Gerber_Drill_PTH.DRL').read_text())
  slots=[h for h in actual if h['slot']]
  pads=[p for p in b['pads'] if p.get('slotPointsMM')]
  self.assertEqual(len(slots),7); self.assertEqual(len(pads),7)
  for p in pads:
   g=LineString(p['slotPointsMM']).buffer(p['drill']/2,quad_segs=64)
   self.assertLess(min(g.hausdorff_distance(h['geometry']) for h in slots),.002)
   self.assertAlmostEqual(LineString(p['slotPointsMM']).length+p['drill'],p['slotLength'],delta=.001)
  npth=parse_drills((m.DEFAULT_GERBER.parent/'Gerber_Drill_NPTH.DRL').read_text())
  source=[g for g in b['graphics'] if g['kind']=='hole']
  self.assertEqual(len(npth),7);self.assertEqual(len(source),7)
  for p in source:
   g=Point(p['x'],p['y']).buffer(p['diameter']/2,quad_segs=64)
   self.assertLess(min(g.hausdorff_distance(h['geometry']) for h in npth),.002)
if __name__=='__main__':unittest.main()
