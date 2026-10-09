/* USART1 output is captured by the backend's Renode file terminal. */
#include "stm32f103.h"

int main(void)
{
    board_uart1_init();
    for (;;) {
        board_uart1_puts("hello from the Cortex-M3\r\n");
        board_delay_ms(250);
    }
}
