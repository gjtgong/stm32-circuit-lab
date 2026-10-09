/* Minimal Cortex-M3 startup for the local STM32F103ZET6 simulation. */
#include <stdint.h>

extern uint32_t _estack;
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;
extern uint32_t _sbss;
extern uint32_t _ebss;

int main(void);

void Reset_Handler(void);
void Default_Handler(void);

void SystemInit(void) __attribute__((weak));
void SystemInit(void)
{
    /* The Renode board starts with the STM32F1 peripheral clock model at
       72 MHz.  Applications may configure RCC themselves when needed. */
}

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;

    while (dst < &_edata) {
        *dst++ = *src++;
    }

    for (dst = &_sbss; dst < &_ebss; ++dst) {
        *dst = 0;
    }

    SystemInit();
    (void)main();

    /* A return from main has no defined meaning on a bare-metal target. */
    for (;;) {
        __asm volatile("wfi");
    }
}

void Default_Handler(void)
{
    for (;;) {
        __asm volatile("wfi");
    }
}

void NMI_Handler(void)             __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void)      __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)             __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)        __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)          __attribute__((weak, alias("Default_Handler")));
/* The lab delay helper uses SysTick as a wake-up source for WFI.  Applications
   may provide their own handler; this weak no-op is safe for polling users. */
void SysTick_Handler(void) __attribute__((weak));
void SysTick_Handler(void) {}

__attribute__((used, section(".isr_vector")))
const uintptr_t vector_table[] = {
    (uintptr_t)&_estack,
    (uintptr_t)Reset_Handler,
    (uintptr_t)NMI_Handler,
    (uintptr_t)HardFault_Handler,
    (uintptr_t)MemManage_Handler,
    (uintptr_t)BusFault_Handler,
    (uintptr_t)UsageFault_Handler,
    0,
    0,
    0,
    0,
    (uintptr_t)SVC_Handler,
    (uintptr_t)DebugMon_Handler,
    0,
    (uintptr_t)PendSV_Handler,
    (uintptr_t)SysTick_Handler,
};
