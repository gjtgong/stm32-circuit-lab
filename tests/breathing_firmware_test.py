#!/usr/bin/env python3
"""Evidence tests for the real V1 onboard-LED breathing firmware.

The integration tests deliberately consume ``server._run_simulation``.  The
assertions are therefore made against timestamped GPIO transitions from the
ARM ELF running in Renode, rather than against a JavaScript animation or an
expected list manufactured by the test.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def low_pulse_widths(events: list[dict[str, object]], pin: str) -> list[float]:
    """Return measured active-low (value 0) pulse widths for one GPIO pin."""
    widths: list[float] = []
    low_started: float | None = None
    state: int | None = None
    for event in events:
        if event["pin"] != pin:
            continue
        value = int(event["value"])
        time_ms = float(event["timeMs"])
        if value == 0 and state != 0:
            low_started = time_ms
        elif value == 1 and state == 0 and low_started is not None:
            widths.append(time_ms - low_started)
            low_started = None
        state = value
    return widths


class BreathingFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        status = server._status()
        cls.skip_reason = None if status["ready"] else "; ".join(status["limitations"][-2:])

    def test_project_records_real_onboard_channels_and_manual_polarity(self) -> None:
        project = json.loads((ROOT / "static/projects/breathe.json").read_text(encoding="utf-8"))
        self.assertIn("GPIOB->BSRR", project["code"])
        self.assertIn("GPIOE->BSRR", project["code"])
        channels = {channel["pin"]: channel for channel in project["trace"]["channels"]}
        self.assertEqual(set(channels), {"PB5", "PE5"})
        self.assertTrue(channels["PB5"]["activeLow"])
        self.assertTrue(channels["PE5"]["activeLow"])
        self.assertEqual(
            {part["signal"]: part["label"] for part in project["parts"] if part["type"] == "led"},
            {
                "PB5": "LED0 / DS0 · PB5 · 红色 · active-low",
                "PE5": "LED1 / DS1 · PE5 · 绿色 · active-low",
            },
        )
        self.assertEqual(
            {(wire["a"], wire["b"]) for wire in project["wires"]},
            {
                ("board:3V3", "r15:1"),
                ("r15:2", "led0:A"),
                ("led0:K", "board:PB5"),
                ("board:3V3", "r19:1"),
                ("r19:2", "led1:A"),
                ("led1:K", "board:PE5"),
            },
        )
        compiler = server._find_toolchain()
        if compiler is not None:
            with tempfile.TemporaryDirectory(prefix="breathe-project-test-") as temp:
                elf, log = server._compile_source(project["code"], Path(temp), compiler)
                self.assertIsNotNone(elf, log)
        manual = (ROOT / "references/LED-CIRCUIT.md").read_text(encoding="utf-8")
        for text in ("LED0 / DS0", "PB5", "LED1 / DS1", "PE5", "KEY_UP", "KEY0", "KEY1"):
            self.assertIn(text, manual)

    def test_breathe_elf_produces_varying_active_low_trace_on_both_leds(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        source = (ROOT / "examples/breathe.c").read_text(encoding="utf-8")
        result = server._run_simulation(source, {})
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["durationMs"], 1999.0)
        self.assertLessEqual(result["durationMs"], 2000.0)

        traces = {
            pin: low_pulse_widths(result["events"], pin)
            for pin in ("PB5", "PE5")
        }
        for pin, widths in traces.items():
            self.assertGreaterEqual(len(widths), 150, pin)
            self.assertLessEqual(min(widths), 1.1, pin)
            self.assertGreaterEqual(max(widths), 8.8, pin)
            self.assertGreaterEqual(len({round(width, 2) for width in widths}), 8, pin)
            peak = max(range(len(widths)), key=widths.__getitem__)
            self.assertGreater(peak, len(widths) * 0.35, pin)
            self.assertLess(peak, len(widths) * 0.65, pin)
            self.assertLess(widths[0], widths[peak], pin)
            self.assertLess(widths[-1], widths[peak], pin)

        # Both physical LEDs receive the same firmware PWM phase; Renode may
        # round adjacent GPIO writes a few microseconds apart.
        for left, right in zip(traces["PB5"][:100], traces["PE5"][:100]):
            self.assertLess(abs(left - right), 0.01)

    def test_fixed_twenty_and_eighty_percent_firmware_duties_are_distinct(self) -> None:
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        template = r'''
#include "stm32f103.h"
#define ON_MS DUTY_ON_MS
static inline void leds_set_on(unsigned char on) {
    if (on) {
        GPIOB->BSRR = 1u << (5u + 16u);
        GPIOE->BSRR = 1u << (5u + 16u);
    } else {
        GPIOB->BSRR = 1u << 5u;
        GPIOE->BSRR = 1u << 5u;
    }
}
int main(void) {
    *RCC_APB2ENR |= (1u << 3) | (1u << 6);
    board_gpio_output(GPIOB, 5);
    board_gpio_output(GPIOE, 5);
    leds_set_on(0);
    for (;;) {
        leds_set_on(1);
        board_delay_ms(ON_MS);
        leds_set_on(0);
        board_delay_ms(10u - ON_MS);
    }
}
'''

        measured: dict[int, float] = {}
        for duty, on_ms in ((20, 2), (80, 8)):
            result = server._run_simulation(template.replace("DUTY_ON_MS", str(on_ms)), {})
            self.assertTrue(result["ok"], result)
            widths = low_pulse_widths(result["events"], "PB5")
            self.assertGreaterEqual(len(widths), 100)
            measured[duty] = sum(widths[:50]) / 50.0

        self.assertAlmostEqual(measured[20], 2.0, delta=0.02)
        self.assertAlmostEqual(measured[80], 8.0, delta=0.02)
        self.assertGreater(measured[80] - measured[20], 5.9)


if __name__ == "__main__":
    unittest.main()
