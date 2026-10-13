/* Uncached MIPS32 return control. Only two SRAM stores; no stack or MMIO. */
    .set noreorder
    .set noat
    .section .entry,"ax",@progbits
    .globl rom_probe
rom_probe:
    lui $8,0xa1c0
    ori $8,$8,0x2000
    lui $9,0x5254
    ori $9,$9,0x4e31
    sw $9,0($8)
    sw $4,4($8)
    lui $2,0x4250
    ori $2,$2,0x5242
    jr $31
    nop
