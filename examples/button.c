/* PA0 input controls the PB0 LED in the local virtual board. */
#include "stm32f103.h"

int main(void)
{
    board_gpio_input(GPIOA, 0);
    board_gpio_output(GPIOB, 0);
    board_uart1_init();

    for (;;) {
        board_gpio_write(GPIOB, 0, board_gpio_read(GPIOA, 0));
        board_delay_ms(1);
    }
}
