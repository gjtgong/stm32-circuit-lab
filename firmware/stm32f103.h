/*
 * Small, dependency-free STM32F103 register header for the lab examples.
 * It intentionally covers the GPIO, RCC, USART1 and SysTick registers used
 * by the first virtual-board lessons.  Applications can still use raw
 * addresses for other peripherals, but those peripherals are not part of the
 * local board model unless documented by the backend.
 */
#ifndef STM32F103_LAB_H
#define STM32F103_LAB_H

#include <stdint.h>

#define __IO volatile

typedef struct {
    __IO uint32_t CRL;
    __IO uint32_t CRH;
    __IO uint32_t IDR;
    __IO uint32_t ODR;
    __IO uint32_t BSRR;
    __IO uint32_t BRR;
    __IO uint32_t LCKR;
} GPIO_TypeDef;

typedef struct {
    __IO uint32_t SR;
    __IO uint32_t DR;
    __IO uint32_t BRR;
    __IO uint32_t CR1;
    __IO uint32_t CR2;
    __IO uint32_t CR3;
    __IO uint32_t GTPR;
} USART_TypeDef;

typedef struct {
    __IO uint32_t CTRL;
    __IO uint32_t LOAD;
    __IO uint32_t VAL;
    __IO uint32_t CALIB;
} SysTick_Type;

#define GPIOA   ((GPIO_TypeDef *)0x40010800u)
#define GPIOB   ((GPIO_TypeDef *)0x40010C00u)
#define GPIOC   ((GPIO_TypeDef *)0x40011000u)
#define GPIOD   ((GPIO_TypeDef *)0x40011400u)
#define GPIOE   ((GPIO_TypeDef *)0x40011800u)
#define GPIOF   ((GPIO_TypeDef *)0x40011C00u)
#define GPIOG   ((GPIO_TypeDef *)0x40012000u)
#define USART1  ((USART_TypeDef *)0x40013800u)
#define SysTick ((SysTick_Type *)0xE000E010u)

#define RCC_APB2ENR ((uint32_t *)0x40021018u)

#define USART_SR_TXE   (1u << 7)
#define USART_SR_TC    (1u << 6)
#define USART_CR1_UE   (1u << 13)
#define USART_CR1_TE   (1u << 3)
#define USART_CR1_RE   (1u << 2)
#define SYSTICK_ENABLE    (1u << 0)
#define SYSTICK_TICKINT   (1u << 1)
#define SYSTICK_CLKSOURCE (1u << 2)
#define SYSTICK_COUNTFLAG (1u << 16)

static inline void board_gpio_output(GPIO_TypeDef *port, uint8_t pin)
{
    __IO uint32_t *configuration = (pin < 8u) ? &port->CRL : &port->CRH;
    uint8_t shift = (uint8_t)((pin & 7u) * 4u);
    uint32_t value = *configuration;

    value &= ~(0xFu << shift);
    /* MODE=11 (50 MHz), CNF=00 (general-purpose push-pull). */
    value |= (0x3u << shift);
    *configuration = value;
}

static inline void board_gpio_input(GPIO_TypeDef *port, uint8_t pin)
{
    __IO uint32_t *configuration = (pin < 8u) ? &port->CRL : &port->CRH;
    uint8_t shift = (uint8_t)((pin & 7u) * 4u);
    uint32_t value = *configuration;

    value &= ~(0xFu << shift);
    /* MODE=00, CNF=01 (floating input). */
    value |= (0x4u << shift);
    *configuration = value;
}

static inline void board_gpio_write(GPIO_TypeDef *port, uint8_t pin, uint8_t state)
{
    uint32_t mask = 1u << pin;
    if (state != 0u) {
        port->BSRR = mask;
    } else {
        port->BRR = mask;
    }
}

static inline uint8_t board_gpio_read(GPIO_TypeDef *port, uint8_t pin)
{
    return (uint8_t)((port->IDR >> pin) & 1u);
}

static inline void board_gpio_toggle(GPIO_TypeDef *port, uint8_t pin)
{
    board_gpio_write(port, pin, (uint8_t)!((port->ODR >> pin) & 1u));
}

static inline void board_uart1_init(void)
{
    /* Enable GPIOA/USART1 clocks and configure a common 115200 baud value.
       The model accepts DR writes even when an application omits this helper. */
    *RCC_APB2ENR |= (1u << 2) | (1u << 14);
    /* USART1 TX (PA9) is alternate-function push-pull; RX (PA10) is input. */
    GPIOA->CRH = (GPIOA->CRH & ~(0xFFu << 4)) | (0xBu << 4) | (0x4u << 8);
    USART1->BRR = 625u; /* 72 MHz / 115200, rounded for a 16x oversampler. */
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE;
}

static inline void board_uart1_putc(char value)
{
    /* Waiting for TXE mirrors the STM32 programming model.  Renode sets TXE
       when USART1 is enabled; the bounded loop keeps a malformed peripheral
       configuration from trapping a lesson forever. */
    uint32_t guard = 100000u;
    while (((USART1->SR & USART_SR_TXE) == 0u) && guard-- != 0u) {
        __asm volatile("nop");
    }
    USART1->DR = (uint32_t)(uint8_t)value;
}

static inline void board_uart1_puts(const char *text)
{
    while (*text != '\0') {
        board_uart1_putc(*text++);
    }
}

static inline void board_delay_ms(uint32_t milliseconds)
{
    /* The local Cortex-M model exposes a 72 MHz SysTick clock. */
    SysTick->LOAD = 72000u - 1u;
    SysTick->VAL = 0u;
    SysTick->CTRL = SYSTICK_ENABLE | SYSTICK_TICKINT | SYSTICK_CLKSOURCE;

    while (milliseconds-- != 0u) {
        while ((SysTick->CTRL & SYSTICK_COUNTFLAG) == 0u) {
            /* Let Renode advance the modeled timer without interpreting
               millions of busy-loop instructions on the host. */
            __asm volatile("wfi");
        }
    }

    SysTick->CTRL = 0u;
}

#endif /* STM32F103_LAB_H */
