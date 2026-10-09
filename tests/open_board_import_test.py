#!/usr/bin/env python3
"""Evidence checks for the source-preserving OpenBoardData converter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/import_open_board.py"
SOURCE = ROOT / "references/open-board/EasyEDA_F103ZET6.Pcb.api.json"
GERBER = ROOT / "references/open-board/gerber/Gerber_BoardOutline.GKO"


def load_converter():
    spec = importlib.util.spec_from_file_location("open_board_converter", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converter = load_converter()


class OpenBoardImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = converter.parse_board(SOURCE, GERBER)

    def test_source_counts_and_no_silent_drop(self) -> None:
        source = self.data["sourceCounts"]
        output = self.data["outputCounts"]
        self.assertEqual(source["topLevelShapeCount"], 1243)
        self.assertEqual(source["topLevelLibCount"], 54)
        self.assertEqual(source["topLevelTrackCount"], 283)
        self.assertEqual(source["topLevelViaCount"], 185)
        self.assertEqual(source["expandedPadCount"], 385)
        self.assertEqual(output["components"], 54)
        self.assertEqual(output["tracks"], source["topLevelTrackCount"])
        self.assertEqual(output["vias"], source["topLevelViaCount"])
        self.assertEqual(output["pads"], source["expandedPadCount"])
        # Every expanded source primitive is represented in one of the typed
        # arrays or in graphics. LIB wrappers become components.
        self.assertEqual(output["graphics"], 1509)
        self.assertEqual(source["expandedShapeCount"], 2403)

    def test_affine_frame_matches_source_outline_and_gerber(self) -> None:
        meta = self.data["meta"]
        transform = meta["coordinateTransform"]
        self.assertEqual(meta["originRaw"], [4020.0, 3272.0])
        self.assertEqual(meta["unitsMmPerRaw"], 0.254)
        self.assertEqual(transform["rawBounds"]["minX"], 4029.4488)
        self.assertEqual(transform["rawBounds"]["maxX"], 4250.31)
        self.assertAlmostEqual(self.data["outlineMM"][1][0], 56.098745, places=6)
        self.assertAlmostEqual(self.data["outlineMM"][0][1], 53.50002, places=5)
        self.assertAlmostEqual(meta["gerberOutline"]["widthMm"], 56.098, places=3)
        self.assertAlmostEqual(meta["gerberOutline"]["heightMm"], 53.5, places=3)
        # Nested pads are already global raw coordinates in EasyEDA. A known
        # H1 pad therefore maps directly, with no footprint-relative offset.
        h1 = next(pad for pad in self.data["pads"] if pad["ref"] == "H1" and pad["number"] == "1")
        self.assertEqual(h1["xRaw"], 4070.0788)
        self.assertEqual(h1["yRaw"], 3652.3152)
        self.assertAlmostEqual(h1["x"], (4070.0788 - 4029.4488) * 0.254, places=5)
        self.assertAlmostEqual(h1["y"], (3662.55 - 3652.3152) * 0.254, places=5)

    def test_headers_mcu_and_led_source_facts(self) -> None:
        components = {component["ref"]: component for component in self.data["components"]}
        for header in [f"H{index}" for index in range(1, 9)]:
            self.assertEqual(len(components[header]["padIds"]), 15, header)
        self.assertEqual(len(components["H9"]["padIds"]), 4)
        self.assertEqual(len(components["U2"]["padIds"]), 144)
        self.assertEqual(components["U2"]["sourceRef"], "F103ZET6")
        led = components["LED1"]
        self.assertEqual(led["value"], "ORH-G36G")
        led_nets = {pad["net"] for pad in self.data["pads"] if pad["ref"] == "LED1"}
        resistor_nets = {pad["net"] for pad in self.data["pads"] if pad["ref"] == "R1"}
        self.assertEqual(led_nets, {"3V3", "LED1_2"})
        self.assertEqual(resistor_nets, {"LED1_2", "GND"})
        self.assertIn("no PB5/PE5 onboard LED", self.data["sourceFacts"]["led1"]["sourceFact"])

    def test_lengths_are_converted_once_and_curve_points_are_not_fabricated(self) -> None:
        # This top-level plated pad carries 6.2992 raw units, i.e. the
        # 1.600 mm contact diameter expected from the source footprint.
        pad = next(pad for pad in self.data["pads"] if pad["id"] == "gge18532")
        self.assertAlmostEqual(pad["width"], 1.6, places=5)
        self.assertEqual(pad["widthRaw"], 6.2992)
        self.assertAlmostEqual(pad["drill"], 2 * 2.13 * 0.254, places=6)
        track = next(track for track in self.data["tracks"] if track["id"] == "gge19390")
        self.assertAlmostEqual(track["width"], 0.254, places=6)
        self.assertEqual(track["widthRaw"], 1.0)
        via = self.data["vias"][0]
        self.assertAlmostEqual(via["diameter"], 2.4 * 0.254, places=6)
        self.assertAlmostEqual(via["drill"], 2 * 0.6 * 0.254, places=6)

        arc = next(graphic for graphic in self.data["graphics"] if graphic["kind"] == "arc")
        self.assertIn("pathRaw", arc)
        self.assertNotIn("pointsMM", arc)
        # Any pointsMM emitted by the converter must be genuine linear board
        # geometry. Curved SVG paths stay raw for SVGLoader sampling.
        self.assertTrue(any(graphic["kind"] == "copper-area" for graphic in self.data["graphics"]))
        for graphic in self.data["graphics"]:
            for point in graphic.get("pointsMM", []):
                self.assertGreaterEqual(point[0], -1.0, (graphic["id"], point))
                self.assertLessEqual(point[0], self.data["meta"]["widthMm"] + 1.0, (graphic["id"], point))
                self.assertGreaterEqual(point[1], -1.0, (graphic["id"], point))
                self.assertLessEqual(point[1], self.data["meta"]["heightMm"] + 1.0, (graphic["id"], point))

    def test_drill_radii_match_manufacturing_diameters(self):
        # EasyEDA's PAD/VIA hole field is a radius; Excellon reports diameter.
        via = next(v for v in self.data['vias'] if v['id'] == 'gge22838')
        self.assertAlmostEqual(via['drill'], 0.305, delta=0.001)
        pad = next(p for p in self.data['pads'] if p['id'] == 'gge18532')
        self.assertAlmostEqual(pad['drill'], 1.083, delta=0.002)

    def test_umd_module_contains_same_counts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="open-board-import-") as directory:
            output = Path(directory) / "open-board-data.js"
            subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            node = subprocess.run(
                ["node", "-e", "const d=require(process.argv[1]); console.log(JSON.stringify({s:d.sourceCounts,o:d.outputCounts,u:d.components.find(c=>c.ref==='U2').padIds.length}));", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        result = json.loads(node.stdout)
        self.assertEqual(result["s"]["topLevelShapeCount"], 1243)
        self.assertEqual(result["s"]["expandedPadCount"], 385)
        self.assertEqual(result["o"]["tracks"], 283)
        self.assertEqual(result["o"]["vias"], 185)
        self.assertEqual(result["u"], 144)


if __name__ == "__main__":
    unittest.main()
