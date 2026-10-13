/* Returning security-read diagnostic for the 0xfc extended arm. No SDK startup,
 * reset or flash writer. True word MMIO; same volatile SPI clock/config init as
 * the hardware-validated JEDEC helper (slow->fast source, 156 MHz selector,
 * HAL config 0x291), then JEDEC/status checks and two 256-byte security passes
 * (opcode 0x48, security address 0x1000, 4 bytes per transaction). Restores the
 * exact saved settings. ROM USB events expose entry, pre-command, post-command
 * and restored checkpoints. Entered through rom_security_entry.S, which switches
 * to the private stack and fetches the argument from the monitor context.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define SPI ((volatile u32 *)0xa7fff000u)
#define SYS ((volatile u32 *)0xa1a00000u)
#define SC (*(volatile u32 *)0xa1a01014u)
#define OUT ((volatile struct result *)0xa1c02000u)
#define EVENT ((void (*)(u32))0x81e03169u)
#define LIMIT 100000u

struct result {
    u32 magic, version, stage, error;
    u32 jedec, status_before, status_after, bytes_first;
    u32 bytes_second, sc_before, commands, reserved0;
    u32 block_before, config_before, clock_before, frequency_before;
    u32 block_after, config_after, clock_after, frequency_after;
    u8 first[256], second[256];
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

/* SDK hal_SpiCmdWithRx sequence, with finite waits and exact register restore.
 * No transmit-only command path. cmd comes only from the literals below.
 */
static int read_command(u32 cmd, u32 address, u32 count, u32 *value)
{
    u32 block, config;
    if (!idle()) return 0;
    block = SPI[1]; config = SPI[5];
    SPI[6] = 3u; /* clear both host-controller FIFOs */
    if (!idle()) return 0;
    SPI[1] = (block & ~0x1ff00u) | (count << 8);
    SPI[5] = (config & ~(3u << 17)) | ((count == 1u ? 0u : count == 3u ? 3u : 2u) << 17);
    if (!idle()) return 0;
    if (cmd == 0x48u) {
        SPI[2] = (address >> 16) & 255u;
        SPI[2] = (address >> 8) & 255u;
        SPI[2] = address & 255u;
        SPI[2] = 0u; /* dummy byte */
    }
    OUT->commands++;
    SPI[0] = (cmd | 0x100u) << 8; /* single-line receive command */
    if (!idle()) return 0;
    *value = SPI[4] >> ((4u - count) * 8u);
    SPI[5] = config;
    SPI[1] = block;
    return idle();
}

static int status(u32 *value)
{
    u32 lo, hi;
    if (!read_command(5u, 0u, 1u, &lo) || !read_command(0x35u, 0u, 1u, &hi)) return 0;
    *value = (lo & 255u) | ((hi & 255u) << 8);
    return 1;
}

u32 __attribute__((section(".text.boot"))) security_body(u32 argument)
{
    volatile struct result *out = OUT;
    u32 sc, v, pass, offset, error = 0u, configured = 0u;
    out->magic = 0x53454352u; out->version = 2u; out->error = 0u;
    out->jedec = out->status_before = out->status_after = 0u;
    out->bytes_first = out->bytes_second = out->commands = out->reserved0 = 0u;
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
    checkpoint(2u);
    if (!read_command(0x9fu, 0u, 3u, &v)) { error = 3u; goto done; }
    out->jedec = v;
    if (v != 0x1660c8u) { error = 4u; goto done; }
    if (!status(&v)) { error = 5u; goto done; }
    out->status_before = v;
    if (v & 3u) { error = 6u; goto done; } /* WIP/WEL must both be clear */
    for (pass = 0u; pass < 2u; ++pass) {
        volatile u8 *dest = pass ? out->second : out->first;
        for (offset = 0u; offset < 256u; offset += 4u) {
            if (!read_command(0x48u, 0x1000u + offset, 4u, &v)) {
                error = 7u; goto done;
            }
            dest[offset] = (u8)v; dest[offset + 1u] = (u8)(v >> 8);
            dest[offset + 2u] = (u8)(v >> 16); dest[offset + 3u] = (u8)(v >> 24);
            if (pass) out->bytes_second = offset + 4u;
            else out->bytes_first = offset + 4u;
        }
    }
    if (!status(&v)) { error = 8u; goto done; }
    out->status_after = v;
    if (out->status_before != v) { error = 9u; goto done; }
    checkpoint(3u);
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
            error = 10u;
        }
    }
    out->block_after = SPI[1]; out->config_after = SPI[5];
    out->clock_after = SYS[0x48 / 4]; out->frequency_after = SYS[0xac / 4];
    if (out->block_after != out->block_before || out->config_after != out->config_before
            || out->clock_after != out->clock_before || out->frequency_after != out->frequency_before)
        error = 11u;
    out->error = error;
    SC = sc;
    checkpoint(4u);
    return error;
}
