#!/usr/bin/env python3
"""Bounded multi-file and externally-built ELF import checks."""
from __future__ import annotations

import base64
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class ProjectImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        status = server._status()
        cls.skip_reason = None if status["ready"] else "; ".join(status["limitations"][-2:])

    def test_two_file_project_runs_helper_code_and_changes_real_gpio(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        files = {
            "app/main.c": """
#include \"gpio_helpers.h\"
int main(void) {
    led_init();
    for (;;) {
        led_write(1);
        board_delay_ms(5);
        led_write(0);
        board_delay_ms(5);
    }
}
""",
            "gpio_helpers.h": """
#ifndef GPIO_HELPERS_H
#define GPIO_HELPERS_H
#include \"stm32f103.h\"
void led_init(void);
void led_write(unsigned char state);
#endif
""",
            "gpio_helpers.c": """
#include \"gpio_helpers.h\"
void led_init(void) {
    board_gpio_output(GPIOB, 0);
}
void led_write(unsigned char state) {
    board_gpio_write(GPIOB, 0, state);
}
""",
        }
        result = server._run_simulation(None, {}, files=files)
        self.assertTrue(result["ok"], result)
        events = [event for event in result["events"] if event["pin"] == "PB0"]
        self.assertGreaterEqual(len(events), 20, result)
        self.assertEqual({event["value"] for event in events}, {0, 1})
        self.assertNotEqual(events[0]["value"], events[1]["value"])

    def test_imported_elf_uses_same_renode_gpio_trace_as_source(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        source = """
#include \"stm32f103.h\"
int main(void) {
    board_gpio_output(GPIOB, 0);
    for (;;) {
        board_gpio_write(GPIOB, 0, 1);
        board_delay_ms(20);
        board_gpio_write(GPIOB, 0, 0);
        board_delay_ms(20);
    }
}
"""
        with tempfile.TemporaryDirectory(prefix="project-import-elf-") as temp:
            elf_path, compile_log = server._compile_source(source, Path(temp), server._find_toolchain())
            self.assertIsNotNone(elf_path, compile_log)
            assert elf_path is not None
            elf = elf_path.read_bytes()

        self.assertIsNone(server._validate_imported_elf(elf))
        source_result = server._run_simulation(source, {})
        imported_result = server._run_simulation(None, {}, elf_bytes=elf)
        self.assertTrue(source_result["ok"], source_result)
        self.assertTrue(imported_result["ok"], imported_result)
        source_events = [event for event in source_result["events"] if event["pin"] == "PB0"]
        imported_events = [event for event in imported_result["events"] if event["pin"] == "PB0"]
        self.assertGreaterEqual(len(source_events), 20)
        self.assertEqual(len(source_events), len(imported_events))
        self.assertEqual(
            [(event["pin"], event["value"]) for event in source_events[:20]],
            [(event["pin"], event["value"]) for event in imported_events[:20]],
        )
        for source_event, imported_event in zip(source_events[:20], imported_events[:20]):
            self.assertAlmostEqual(source_event["timeMs"], imported_event["timeMs"], places=3)

        decoded_source, decoded_files, decoded_elf, error = server._decode_run_firmware(
            {"elfBase64": base64.b64encode(elf).decode("ascii")}
        )
        self.assertIsNone(error)
        self.assertIsNone(decoded_source)
        self.assertIsNone(decoded_files)
        self.assertEqual(decoded_elf, elf)

    def test_invalid_project_paths_and_wrong_elf_are_rejected_before_run(self) -> None:
        for files, expected in (
            ({"../escape.c": "int main(void) { }"}, ".."),
            ({"/tmp/escape.c": "int main(void) { }"}, "absolute"),
            ({"main.txt": "int main(void) { }"}, ".c and .h"),
        ):
            source, project, elf, error = server._decode_run_firmware({"files": files})
            self.assertIsNone(source)
            self.assertIsNone(project)
            self.assertIsNone(elf)
            self.assertIn(expected, error or "")

        source, project, elf, error = server._decode_run_firmware(
            {"elfBase64": base64.b64encode(b"this is not an ELF").decode("ascii")}
        )
        self.assertIsNone(source)
        self.assertIsNone(project)
        self.assertIsNone(elf)
        self.assertIn("ELF", error or "")

        result = server._run_simulation(None, {}, files={"../escape.c": "int main(void) { }"})
        self.assertFalse(result["ok"])
        self.assertIn("unsafe project path", result["log"])
        result = server._run_simulation(None, {}, elf_bytes=b"this is not an ELF")
        self.assertFalse(result["ok"])
        self.assertIn("imported ELF invalid", result["log"])


if __name__ == "__main__":
    unittest.main()
