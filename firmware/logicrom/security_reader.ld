ENTRY(security_reader)
SECTIONS {
  . = 0x81c00280;
  .text : { *(.entry) *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) }
  .bss : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.comment) *(.note*) *(.pdr) *(.reginfo) *(.mdebug*) *(.gnu.attributes) }
  ASSERT(. < 0x81c02000, "reader overlaps result SRAM")
}
