/* Returning single-command diagnostic. No SDK startup, reset or flash writer.
 * True word MMIO; change only SPI source/frequency/config, restore exact values.
 * ROM USB events expose entry, pre-command, post-command and restored checkpoints.
 *
 * Default build: rom_probe in .entry for the 0xff executor arm (disabled).
 * JEDEC_VIA_EXTENDED build: jedec_body for the 0xfc extended arm, entered
 * through the rom_jedec_entry.S stub (switches to the private stack, fetches
 * the argument from the monitor context). The body is arm-agnostic.
 */
typedef unsigned int u32;
#define SPI ((volatile u32 *)0xa7fff000u)
#define SYS ((volatile u32 *)0xa1a00000u)
#define SC (*(volatile u32 *)0xa1a01014u)
#define OUT ((volatile struct result *)0xa1c02000u)
#define EVENT ((void (*)(u32))0x81e03169u)
#define LIMIT 100000u

struct result {
    u32 magic, version, stage, error, jedec, sc_before;
    u32 block_before, config_before, clock_before, frequency_before;
    u32 block_after, config_after, clock_after, frequency_after, commands, reserved;
};

static int idle(void)
{
    u32 count;
    for (count = LIMIT; count && (SPI[3] & 1u); --count) {}
    if (!count) return 0;
    for (count = LIMIT; count && (SPI[3] & 1u); --count) {}
    return count != 0;
}

static void checkpoint(u32 stage)
{
    OUT->stage = stage;
    EVENT(0x53500000u | stage);
}

#if defined(JEDEC_VIA_EXTENDED)
#define ENTRY_NAME jedec_body
#define ENTRY_SECTION ".text.boot"
#else
#define ENTRY_NAME rom_probe
#define ENTRY_SECTION ".entry"
#endif

u32 __attribute__((section(ENTRY_SECTION))) ENTRY_NAME(u32 argument)
{
    volatile struct result *out = OUT;
    u32 sc, error = 0u, configured = 0u;
    out->magic = 0x4a454443u; out->version = 1u; out->error = 0u;
    out->jedec = out->commands = out->reserved = 0u;
    out->block_before = SPI[1]; out->config_before = SPI[5];
    out->clock_before = SYS[0x48 / 4]; out->frequency_before = SYS[0xac / 4];
    checkpoint(1u);
    sc = SC;
    out->sc_before = sc;
    if (argument != 0x13579bdfu || out->block_before != 0x100u
            || out->config_before != 0x8a0u || out->clock_before != 0x5f16u
            || out->frequency_before != 2u || (SYS[0x44 / 4] & 0x1011u) != 0x1011u) {
        error = 1u; goto done;
    }
    if (!idle()) { error = 2u; goto done; }
    SYS[0] = 0xa50001u;
    SYS[0x48 / 4] = out->clock_before & ~0x400u;
    SYS[0xac / 4] = 9u;
    SYS[0] = 0xa50000u;
    SPI[5] = 0x291u;
    configured = 1u;
    if (!idle()) { error = 3u; goto done; }
    SPI[6] = 3u;
    if (!idle()) { error = 4u; goto done; }
    SPI[1] = (out->block_before & ~0x1ff00u) | 0x300u;
    SPI[5] = 0x60291u;
    if (!idle()) { error = 5u; goto done; }
    checkpoint(2u);
    out->commands = 1u;
    SPI[0] = 0x19f00u; /* single-line 9f, exactly once */
    if (!idle()) { error = 6u; goto done; }
    out->jedec = SPI[4] >> 8;
    checkpoint(3u);
    if (out->jedec != 0x1660c8u) error = 7u;
done:
    if (configured) {
        if (idle()) {
            SPI[5] = out->config_before;
            SPI[1] = out->block_before;
            SYS[0] = 0xa50001u;
            SYS[0xac / 4] = out->frequency_before;
            SYS[0x48 / 4] = out->clock_before;
            SYS[0] = 0xa50000u;
        } else {
            error = 8u;
        }
    }
    out->block_after = SPI[1]; out->config_after = SPI[5];
    out->clock_after = SYS[0x48 / 4]; out->frequency_after = SYS[0xac / 4];
    if (out->block_after != out->block_before || out->config_after != out->config_before
            || out->clock_after != out->clock_before || out->frequency_after != out->frequency_before)
        error = 9u;
    out->error = error;
    SC = sc;
    checkpoint(4u);
    return error;
}
