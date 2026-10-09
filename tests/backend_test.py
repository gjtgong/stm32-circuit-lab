#!/usr/bin/env python3
"""Backend smoke and Renode integration checks.

Run with ``python3 -m unittest discover -s tests -p 'backend*.py'``. The
compile checks run on a host with arm-none-eabi-gcc; Renode checks are skipped
with an explicit reason when the portable runtime has not been extracted yet.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class BackendCompileTests(unittest.TestCase):
    def test_example_links_with_stm32_memory_map(self) -> None:
        compiler = server._find_toolchain()
        if compiler is None:
            self.skipTest("arm-none-eabi-gcc is unavailable")
        with __import__("tempfile").TemporaryDirectory(prefix="stm32-backend-test-") as temp:
            elf, log = server._compile_source((ROOT / "examples" / "blink.c").read_text(), pathlib.Path(temp), compiler)
            self.assertIsNotNone(elf, log)
            self.assertTrue((pathlib.Path(temp) / "firmware.elf").is_file())
            readelf = shutil.which("arm-none-eabi-readelf")
            if readelf:
                symbols = subprocess.run(
                    [readelf, "-sW", str(elf)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(symbols.returncode, 0, symbols.stderr)
                vector_rows = [line for line in symbols.stdout.splitlines() if " vector_table" in line]
                self.assertTrue(vector_rows, symbols.stdout)
                self.assertTrue(any("08000000" in line for line in vector_rows), vector_rows)

    def test_compile_error_is_returned_without_running_renode(self) -> None:
        compiler = server._find_toolchain()
        if compiler is None:
            self.skipTest("arm-none-eabi-gcc is unavailable")
        with __import__("tempfile").TemporaryDirectory(prefix="stm32-backend-test-") as temp:
            elf, log = server._compile_source(
                '#include "stm32f103.h"\nint main(void) { this is not valid C; }\n',
                pathlib.Path(temp),
                compiler,
            )
            self.assertIsNone(elf)
            self.assertIn("user code compile failed", log)


class RenodeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        status = server._status()
        if not status["ready"]:
            cls.skip_reason = "Renode/ARM toolchain unavailable: " + "; ".join(status["limitations"][-2:])
        else:
            cls.skip_reason = None

    def test_changed_delay_changes_real_gpio_trace(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        template = """
#include \"stm32f103.h\"
int main(void) {
    board_gpio_output(GPIOB, 0);
    for (;;) {
        board_gpio_write(GPIOB, 0, 1);
        board_delay_ms(DELAY);
        board_gpio_write(GPIOB, 0, 0);
        board_delay_ms(DELAY);
    }
}
"""
        fast = server._run_simulation(template.replace("DELAY", "5"), {})
        slow = server._run_simulation(template.replace("DELAY", "20"), {})
        self.assertTrue(fast["ok"], fast)
        self.assertTrue(slow["ok"], slow)
        fast_times = [event["timeMs"] for event in fast["events"] if event["pin"] == "PB0"]
        slow_times = [event["timeMs"] for event in slow["events"] if event["pin"] == "PB0"]
        self.assertGreaterEqual(len(fast_times), 4, fast)
        self.assertGreaterEqual(len(slow_times), 4, slow)
        self.assertNotEqual(fast_times[1] - fast_times[0], slow_times[1] - slow_times[0])

    def test_pa0_input_reaches_real_firmware(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        source = """
#include \"stm32f103.h\"
    int main(void) {
        board_gpio_input(GPIOA, 0);
        board_gpio_output(GPIOB, 0);
        board_gpio_write(GPIOB, 0, 1);
        for (;;) {
        board_gpio_write(GPIOB, 0, board_gpio_read(GPIOA, 0));
        board_delay_ms(2);
    }
}
"""
        low = server._run_simulation(source, {"PA0": 0})
        high = server._run_simulation(source, {"PA0": 1})
        self.assertTrue(low["ok"], low)
        self.assertTrue(high["ok"], high)
        low_values = {event["value"] for event in low["events"] if event["pin"] == "PB0"}
        high_values = {event["value"] for event in high["events"] if event["pin"] == "PB0"}
        self.assertIn(0, low_values)
        self.assertIn(1, high_values)


if __name__ == "__main__":
    unittest.main()
