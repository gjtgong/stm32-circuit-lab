/* STM32F103ZET6 virtual-board example: PB0 LED blink. */
#include "stm32f103.h"

int main(void)
{
    board_gpio_output(GPIOB, 0);
    board_uart1_init();
    board_uart1_puts("STM32F103ZET6 PB0 blink\r\n");

    for (;;) {
        board_gpio_write(GPIOB, 0, 1);
        board_delay_ms(100);
        board_gpio_write(GPIOB, 0, 0);
        board_delay_ms(100);
    }
}
