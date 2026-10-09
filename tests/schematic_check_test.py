import sys,json,copy,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from schematic_check import schematic_graph,compare

def lib(ref,number,x,y,id=None):
    annotation=['T','P','0','0','0','#fff','','','','','','comment',ref,'1']
    pin=f'P~show~0~{number}~{x}~{y}~0~pin-{ref}-{number}^^{x}~{y}^^M {x} {y} h10~#fff^^1~0~0~0~test^^1~0~0~0~{number}'
    return f'LIB~0~0~package`TEST`~0~0~{id or ref}#@$'+ '~'.join(annotation)+'#@$'+pin

def wire(points):return 'W~'+points+'~#fff~1~0~none~w'
def label(name,x,y):return f'N~{x}~{y}~0~#fff~{name}~n'
def pcbpad(ref,number,net):return {'id':ref+number,'ref':ref,'number':number,'net':net}
def graph(shapes):return schematic_graph({'shape':shapes})

class SchematicGraphTests(unittest.TestCase):
    def crossing(self,extra=()):return graph([lib('A','1',-1,0),lib('B','1',0,-1),wire('-1 0 1 0'),wire('0 -1 0 1'),*extra])
    def test_unmarked_interior_crossing_is_not_connected(self):
        g=self.crossing();self.assertNotEqual(g['pins']['A:1']['group'],g['pins']['B:1']['group'])
    def test_explicit_junction_connects_crossing(self):
        g=self.crossing(['J~0~0~2.5~#fff~j']);self.assertEqual(g['pins']['A:1']['group'],g['pins']['B:1']['group'])
    def test_t_endpoint_connects(self):
        g=graph([lib('A','1',-1,0),lib('B','1',0,-1),wire('-1 0 1 0'),wire('0 -1 0 0')])
        self.assertEqual(g['pins']['A:1']['group'],g['pins']['B:1']['group'])
    def test_named_distant_segments_join(self):
        g=graph([lib('A','1',0,0),lib('B','1',10,0),label('GND',0,0),label('GND',10,0)])
        self.assertEqual(len(g['groups']),1)
    def test_nc_flag_at_wire_stub_preserves_intent(self):
        g=graph([lib('A','1',0,0),wire('0 0 1 0'),'O~1~0~nc'])
        self.assertTrue(g['pins']['A:1']['noConnect']);self.assertEqual(g['issues'],[])
    def test_nc_flag_does_not_hide_connected_pin(self):
        g=graph([lib('A','1',0,0),lib('B','1',1,0),wire('0 0 1 0'),'O~1~0~nc'])
        self.assertFalse(g['pins']['A:1']['noConnect']);self.assertEqual(g['issues'][0]['type'],'no_connect_is_connected')
    def test_multiple_labels_preserved_for_review(self):
        g=graph([lib('A','1',0,0),label('3V3',0,0),label('GND',0,0)])
        self.assertEqual(g['labelAliasGroups'][0]['labels'],['3V3','GND'])
        self.assertTrue(g['labelAliasGroups'][0]['requiresReview'])
    def test_unsupported_bus_rejected(self):
        with self.assertRaises(ValueError):graph(['B~0 0 10 0'])

class SchematicCompareTests(unittest.TestCase):
    def test_pcb_splits_schematic_net(self):
        g=graph([lib('A','1',0,0),lib('B','1',1,0),wire('0 0 1 0')])
        r=compare({'pads':[pcbpad('A','1','X'),pcbpad('B','1','Y')]},g)
        self.assertTrue(any(i['type']=='schematic_net_split_in_pcb' for i in r['networkIssues']))
    def test_pcb_merges_separate_schematic_groups(self):
        g=graph([lib('A','1',0,0),lib('B','1',1,0)])
        r=compare({'pads':[pcbpad('A','1','X'),pcbpad('B','1','X')]},g)
        self.assertTrue(any(i['type']=='pcb_net_merges_schematic_groups' for i in r['networkIssues']))
    def test_missing_pcb_net_and_connected_nc_reported(self):
        g=graph([lib('A','1',0,0),label('PA0',0,0),lib('B','1',10,0),'O~10~0~nc'])
        r=compare({'pads':[pcbpad('A','1',None),pcbpad('B','1','PA0')]},g)
        self.assertEqual({i['type'] for i in r['networkIssues']},{'schematic_pin_missing_pcb_net','no_connect_has_pcb_net'})
    def test_identity_alias_uses_component_id(self):
        g=graph([lib('BOOT1','1',0,0,'same')])
        p=pcbpad('BOOT','1','X');p['componentId']='same'
        r=compare({'pads':[p],'components':[{'id':'same','ref':'BOOT'}]},g)
        self.assertEqual(r['summary']['matchedTerminals'],1);self.assertEqual(r['referenceAliases'][0]['schematicRef'],'BOOT1')
    def test_duplicate_pad_terminal_conflict_is_not_given_a_guessed_net(self):
        g=graph([lib('A','1',0,0)])
        r=compare({'pads':[pcbpad('A','1','X'),pcbpad('A','1','Y')]},g)
        self.assertEqual(r['terminalStatus'][0]['state'],'mismatch')
        self.assertEqual(r['networkIssues'][0]['type'],'duplicate_terminal_network_conflict')
    def test_unreferenced_pads_not_guessed_by_net(self):
        g=graph([lib('A','1',0,0),label('X',0,0)])
        p=pcbpad('', '1','X');p['ref']=None
        r=compare({'pads':[p]},g)
        self.assertEqual(r['summary']['matchedTerminals'],0);self.assertEqual(r['summary']['unmappedPcbPads'],1)

class ActualSchematicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import import_open_board as m
        path=m.ROOT/'references/open-board/EasyEDA_project-with-schematic.api.json'
        if not path.exists() or not m.DEFAULT_SOURCE.exists():raise unittest.SkipTest('Acquire board source first')
        data=json.loads(path.read_text())['result']['schematics'][0]['dataStr'];cls.doc=json.loads(data)if isinstance(data,str)else data
        cls.board=m.parse_board();cls.graph=schematic_graph(cls.doc)
    def test_real_nc_markers_and_unmapped_identity_report(self):
        r=compare(self.board,self.graph)
        self.assertEqual(r['summary']['matchedTerminals'],364)
        self.assertEqual(r['summary']['explicitNoConnectMatched'],6)
        self.assertEqual(r['networkIssues'],[])
        self.assertEqual(r['missingPcbTerminals'],['X1:1','X1:2'])
        self.assertEqual(r['summary']['unmappedPcbPads'],16)
    def test_real_pcb_pin_swap_is_detected(self):
        b=copy.deepcopy(self.board)
        for p in b['pads']:
            if p.get('ref')=='U2' and p.get('number')=='1':p['net']='PE3'
        r=compare(b,self.graph)
        self.assertTrue(any(i['type']=='label_mismatch' and i['terminal']=='U2:1' for i in r['networkIssues']))
    def test_removing_real_nc_marker_is_not_silently_accepted(self):
        d=copy.deepcopy(self.doc);d['shape']=[s for s in d['shape'] if not s.startswith('O~300~-475~')]
        r=compare(self.board,schematic_graph(d))
        self.assertTrue(any(i['type']=='schematic_pin_missing_pcb_net' and i['terminal']=='U2:106' for i in r['networkIssues']))
