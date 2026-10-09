import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server

class PcbReportTests(unittest.TestCase):
    def test_report_rejects_changed_source_and_unknown_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            inputs=['references/open-board/EasyEDA_F103ZET6.Pcb.api.json','references/open-board/gerber/Gerber_TopLayer.GTL','references/open-board/gerber/Gerber_BottomLayer.GBL']
            hashes={}
            for name in inputs:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original')
                hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
            report=root/'reports/gerber-check.json';report.parent.mkdir()
            report.write_text(json.dumps({'inputHashes':hashes,'summary':{}}))
            with patch.object(server,'ROOT',root):
                self.assertEqual(server.load_pcb_report()['inputHashes'],hashes)
                (root/inputs[0]).write_bytes(b'changed')
                with self.assertRaises(ValueError):server.load_pcb_report()
                hashes['../../other']='abc';report.write_text(json.dumps({'inputHashes':hashes}))
                with self.assertRaises(ValueError):server.load_pcb_report()

    def test_schematic_report_rejects_changed_schematic(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            inputs=['references/open-board/EasyEDA_F103ZET6.Pcb.api.json','references/open-board/EasyEDA_project-with-schematic.api.json']
            hashes={}
            for name in inputs:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original')
                hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
            report=root/'reports/schematic-check.json';report.parent.mkdir()
            report.write_text(json.dumps({'inputHashes':hashes}))
            with patch.object(server,'ROOT',root):
                self.assertEqual(server.load_schematic_report()['inputHashes'],hashes)
                (root/inputs[1]).write_bytes(b'changed')
                with self.assertRaises(ValueError):server.load_schematic_report()
