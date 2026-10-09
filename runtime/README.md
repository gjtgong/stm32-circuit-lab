# STM32F103 Renode runtime

The backend launches a local Renode portable runtime and loads
`stm32f103.repl`. The platform is deliberately offline and bounded:

- one 512 KiB flash object at the STM32F1 address `0x08000000` and reset-vector
  alias `0x00000000`, plus 64 KiB SRAM at `0x20000000`;
- Cortex-M3 CPU with NVIC/SysTick at a 72 MHz model frequency;
- STM32F1 GPIO ports A through G with external-control GPIO state events;
- USART1 at `0x40013800`, captured through Renode's file terminal backend;
- mapped RCC and AFIO storage for ordinary enable/configuration writes.

The MVP does not model ADC, USB, CAN, SDIO, SPI, I2C sensor devices, DMA,
hardware PWM/advanced timers, or the full RCC/AFIO clock tree. GPIO bit-bang
pulses still appear in the trace, while hardware-timer PWM is reported as
unsupported. The `/api/status` response reports these limitations. A run
advances at most 2 seconds of Renode virtual time and is killed after 15
seconds of wall time.

The server looks for Renode in this order:

1. `STM32_LAB_RENODE` or `RENODE_BIN`;
2. `runtime/renode/renode` (the portable archive extracted locally);
3. `renode` on `PATH`.

Use `python3 server.py` to serve the API on `127.0.0.1:8765`.
