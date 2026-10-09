/*
 * ALIENTEK 精英 STM32F103 V1 onboard LED breathing example.
 *
 * DS0 (LED0) is PB5 and DS1 (LED1) is PE5.  Their anodes are tied to
 * 3.3 V through 510 ohm resistors, so a GPIO LOW sinks current and lights
 * the LED.  The code therefore uses the BSRR set/reset halves directly:
 *   - reset bit (pin + 16) -> LOW -> LED on
 *   - set bit (pin)         -> HIGH -> LED off
 *
 * This is deliberately software PWM.  One 10 ms PWM frame is followed by
 * a 20 ms brightness step, giving a roughly 1.98 s low-high-low cycle in the
 * lab's 2 s Renode capture.  Both LEDs are driven from the same trace phase.
 */
#include "stm32f103.h"

#define LED0_PIN              5u /* GPIOB/PB5, red DS0 */
#define LED1_PIN              5u /* GPIOE/PE5, green DS1 */
#define PWM_PERIOD_MS         10u
#define PWM_FRAMES_PER_STEP    2u
#define BREATH_STEPS          50u
#define MIN_BRIGHTNESS         10u
#define MAX_BRIGHTNESS         90u

static inline void onboard_leds_set_on(uint8_t on)
{
    const uint32_t led0 = 1u << LED0_PIN;
    const uint32_t led1 = 1u << LED1_PIN;

    if (on != 0u) {
        /* BSRR upper half resets the pin: active-low LED turns on. */
        GPIOB->BSRR = led0 << 16;
        GPIOE->BSRR = led1 << 16;
    } else {
        /* BSRR lower half sets the pin: active-low LED turns off. */
        GPIOB->BSRR = led0;
        GPIOE->BSRR = led1;
    }
}

static void pwm_frame(uint32_t brightness_percent)
{
    const uint32_t on_ms = (PWM_PERIOD_MS * brightness_percent) / 100u;
    const uint32_t off_ms = PWM_PERIOD_MS - on_ms;

    onboard_leds_set_on(1u);
    board_delay_ms(on_ms);
    onboard_leds_set_on(0u);
    board_delay_ms(off_ms);
}

static void hold_brightness(uint32_t brightness_percent)
{
    for (uint32_t frame = 0; frame < PWM_FRAMES_PER_STEP; ++frame) {
        pwm_frame(brightness_percent);
    }
}

static uint32_t brightness_for_step(uint32_t step)
{
    return MIN_BRIGHTNESS +
        ((MAX_BRIGHTNESS - MIN_BRIGHTNESS) * step) / (BREATH_STEPS - 1u);
}

int main(void)
{
    /* The V1 manual enables GPIOB/GPIOE APB2 clocks before configuring PB5/PE5. */
    *RCC_APB2ENR |= (1u << 3) | (1u << 6);
    board_gpio_output(GPIOB, LED0_PIN);
    board_gpio_output(GPIOE, LED1_PIN);
    onboard_leds_set_on(0u);

    for (;;) {
        for (uint32_t step = 0; step < BREATH_STEPS; ++step) {
            hold_brightness(brightness_for_step(step));
        }
        for (int32_t step = (int32_t)BREATH_STEPS - 2; step >= 0; --step) {
            hold_brightness(brightness_for_step((uint32_t)step));
        }
    }
}
