/* Entry stub for the 0xfc extended-handler arm (boot_HstMonitorExtendedHandler).
 * That arm calls the handler with a0 = &boot_HstMonitorXCtx (0xa1c000a0) on the
 * parser's own KSEG0 stack: it neither switches sp nor passes the host argument.
 * Switch to the private KSEG1 stack (0xa1c04000, 512 bytes reserved), fetch the
 * argument from context word param (0xa1c000ac), run the arm-agnostic body,
 * then restore the incoming sp/s0/ra exactly. Only t0/t1 are clobbered; s0 is
 * preserved on the new stack. Return value v0 is passed through (the arm
 * discards it; the result block is the channel).
 */
    .set noreorder
    .set noat
    .section .entry,"ax",@progbits
    .globl rom_probe
rom_probe:
    lui $9,0xa1c0
    ori $9,$9,0x4000
    addiu $9,$9,-16
    sw $29,0($9)          /* incoming parser stack pointer */
    sw $16,4($9)          /* s0 preserved for the caller */
    sw $31,8($9)          /* return into the MIPS16 parser (0x81e03459) */
    move $29,$9           /* private stack active from here */
    move $16,$9           /* frame base survives the body call */
    lui $8,0xa1c0
    lw $4,0xac($8)        /* argument = boot_HstMonitorXCtx.param */
    jal jedec_body
    nop
    move $9,$16
    lw $31,8($9)
    lw $16,4($9)
    lw $29,0($9)          /* parser stack restored before return */
    jr $31
    nop
