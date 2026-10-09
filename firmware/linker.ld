/*
 * Minimal STM32F103ZET6 memory map used by the local Renode board.
 *
 * The local platform maps one 512 KiB flash object at both the STM32F1 reset
 * alias (0x00000000) and the hardware flash address (0x08000000). The ELF
 * keeps the hardware address, while reset fetches through the alias. Peripheral
 * addresses retain STM32F1 values.
 */
ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } > FLASH

    .text :
    {
        . = ALIGN(4);
        *(.text.Reset_Handler)
        *(.text*)
        *(.rodata*)
        KEEP(*(.init))
        KEEP(*(.fini))
        . = ALIGN(4);
        _etext = .;
    } > FLASH

    .ARM.exidx :
    {
        . = ALIGN(4);
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
        . = ALIGN(4);
    } > FLASH

    _sidata = LOADADDR(.data);

    .data : AT (ADDR(.text) + SIZEOF(.text) + SIZEOF(.ARM.exidx))
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > RAM

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM

    . = ALIGN(8);
    _end = .;

    /DISCARD/ :
    {
        *(.comment)
        *(.note*)
    }
}

ASSERT(SIZEOF(.isr_vector) + SIZEOF(.text) + SIZEOF(.ARM.exidx) + SIZEOF(.data) <= LENGTH(FLASH), "firmware does not fit in 512 KiB flash")
ASSERT(SIZEOF(.data) + SIZEOF(.bss) <= LENGTH(RAM), "firmware data does not fit in 64 KiB SRAM")
