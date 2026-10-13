/* Independent V24 entry markers; no SDK calls, UART opens, or flash writes.
 * GPIO4 blue and GPIO27 red are confirmed in docs/knowledge/pin-map.md.
 * Save/restore pad function and direction: GPIO4 also carries UART2 RX.
 */
#ifndef V24_DIAG_H
#define V24_DIAG_H

typedef unsigned int v24_word;
#define V24_REG(address) (*(volatile v24_word *)(address))
#define V24_GPIO 0xa1a03000u
#define V24_BLUE_PAD 0xa1a2a0a0u
#define V24_RED_PAD 0xa1a2a0b8u
#define V24_TICKS 0xa1a02014u

static void v24_wait_ticks(v24_word duration)
{
    const v24_word start = V24_REG(V24_TICKS);
    v24_word guard;
    for (guard = 0; guard < 2000000u; ++guard) {
        if ((v24_word)(V24_REG(V24_TICKS) - start) >= duration)
            break;
    }
}

static void v24_entry_marker(int red)
{
    const v24_word mask = 1u << (red ? 27 : 4);
    const v24_word pad = red ? V24_RED_PAD : V24_BLUE_PAD;
    const v24_word saved_pad = V24_REG(pad);
    const v24_word saved_input = V24_REG(V24_GPIO) & mask;
    const v24_word saved_level = V24_REG(V24_GPIO + 0x0cu) & mask;

    /* Set latch before exposing output, then select GPIO without pad overrides. */
    V24_REG(V24_GPIO + 0x14u) = mask;
    V24_REG(V24_GPIO + 0x04u) = mask;
    V24_REG(pad) = (saved_pad & ~((1u << 28) | (1u << 24) | 15u))
                  | (red ? 1u : 0u);
    /* Dark gaps make the pulse visible even if the core already lit this LED.
     * 1311 ticks ~80 ms; 4096 ticks = 250 ms. Every wait has a finite guard. */
    v24_wait_ticks(1311u);
    V24_REG(V24_GPIO + 0x10u) = mask;
    v24_wait_ticks(4096u);
    V24_REG(V24_GPIO + 0x14u) = mask;
    v24_wait_ticks(1311u);
    V24_REG(V24_GPIO + (saved_level ? 0x10u : 0x14u)) = mask;
    V24_REG(V24_GPIO + (saved_input ? 0x08u : 0x04u)) = mask;
    V24_REG(pad) = saved_pad;
}

#endif
