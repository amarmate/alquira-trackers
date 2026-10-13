ENTRY(rom_probe)
SECTIONS {
  . = 0xa1c01000;
  .text : { *(.entry) *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) }
  .bss : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.comment) *(.note*) *(.pdr) *(.reginfo) *(.mdebug*) *(.gnu.attributes) }
  ASSERT(. < 0xa1c02000, "probe overlaps result SRAM")
}
