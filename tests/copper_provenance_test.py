import sys,unittest
from pathlib import Path
from shapely.geometry import Polygon,box,LineString
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from copper_provenance import text_geometry,associate_sources
TRANSFORM={'rawOrigin':[0,0],'scale':[1,1]}

def cluster(g,layer=1):
    return {'id':'test','areaMm2':g.area,'geometry':[{'layer':layer,'exterior':list(g.exterior.coords),'holes':[list(r.coords) for r in g.interiors]}]}
def board(graphics):return {'graphics':graphics,'meta':{'coordinateTransform':TRANSFORM}}
def text(path,layer=1):return {'id':'label','kind':'text','layer':layer,'pathRaw':path,'width':.1,'text':'test'}

class CopperProvenanceTests(unittest.TestCase):
    def test_closed_glyph_preserves_void(self):
        g=text_geometry(text('M0 0 L3 0 L3 3 L0 3 Z M1 1 L2 1 L2 2 L1 2 Z'),TRANSFORM)
        self.assertAlmostEqual(g.area,8)
        self.assertFalse(g.contains(box(1.1,-1.9,1.9,-1.1)))
    def test_cubic_coordinates_and_inverted_axis(self):
        g=text_geometry(text('M0 0 C0 1 1 1 1 0 L0 0 Z'),TRANSFORM)
        self.assertAlmostEqual(g.area,.6,delta=.002)
        self.assertAlmostEqual(g.bounds[1],-.75,delta=.001)
    def test_nearby_text_bbox_does_not_explain_copper(self):
        g=text('M0 0 L3 0 L3 3')
        c=cluster(box(.5,-2,.8,-1.7))
        associate_sources(board([g]),[c])
        self.assertEqual(c['provenance']['category'],'unresolved')
        self.assertEqual(c['provenance']['evidence'],[])
    def test_other_layer_does_not_associate(self):
        g=text('M0 0 L1 0 L1 1 L0 1 Z',2)
        c=cluster(box(0,-1,1,0),1)
        associate_sources(board([g]),[c])
        self.assertEqual(c['provenance']['coveredFraction'],0)
    def test_unsupported_path_remains_unresolved(self):
        c=cluster(box(0,0,1,1))
        r=associate_sources(board([text('M0 0 A1 1 0 0 1 1 1')]),[c])
        self.assertEqual(c['provenance']['category'],'unresolved')
        self.assertEqual(r['unsupportedSourceGraphics'][0]['id'],'label')
    def test_pad_artwork_before_drilling_and_extra_copper(self):
        p=dict(id='pad',net=None,ref='SW1',number='1',shape='RECT',width=2,height=2,drill=1,layer=11,x=0,y=0,plated='Y')
        c=cluster(box(-1,-1,1,1))
        associate_sources({'pads':[p]},[c])
        self.assertEqual(c['provenance']['category'],'unnamed-pad')
        self.assertEqual(c['provenance']['evidence'][0]['plannedDrillMm'],1)
        self.assertTrue(c['provenance']['requiresReview'])
        extra=cluster(box(-1,-1,2,1))
        associate_sources({'pads':[p]},[extra])
        self.assertEqual(extra['provenance']['category'],'unresolved')
        self.assertGreater(extra['provenance']['outsideSourceAreaMm2'],1.9)
    def test_unsupported_commands_are_not_silently_removed(self):
        for path in ('M0 0 Q1 1 2 2','m0 0 l1 1','M0 0 L','M0 0 @ L1 1'):
            with self.assertRaises(ValueError):text_geometry(text(path),TRANSFORM)
