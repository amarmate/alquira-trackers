/* RAM-only returning ROM helper. No SDK startup and no flash writer linked.
 * Fixed read commands: JEDEC (9f), SR1 (05), SR2 (35), security (48).
 * Result resides in internal SRAM, not the flash/main-array address space.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define SPI ((volatile u32 *)0xa7fff000u)
#define SC (*(volatile u32 *)0xa1a01014u)
#define OUT ((volatile struct result *)0xa1c02000u)
#define MAGIC 0x53454352u
#define LIMIT 1000000u

struct result {
    u32 magic, version, state, error;
    u32 jedec, status_before, status_after, bytes_first, bytes_second;
    u32 block_before, config_before, block_after, config_after;
    u8 first[256], second[256];
};

static int idle(void)
{
    u32 guard;
    for (guard = LIMIT; guard && (SPI[3] & 1u); --guard) {}
    if (!guard) return 0;
    for (guard = LIMIT; guard && (SPI[3] & 1u); --guard) {}
    return guard != 0;
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
    SPI[5] = (config & ~(3u << 17)) | ((count == 1 ? 0u : count == 3 ? 3u : 2u) << 17);
    if (!idle()) return 0;
    if (cmd == 0x48u) {
        SPI[2] = (address >> 16) & 255u;
        SPI[2] = (address >> 8) & 255u;
        SPI[2] = address & 255u;
        SPI[2] = 0u; /* dummy byte */
    }
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

u32 __attribute__((section(".entry"))) security_reader(void)
{
    volatile struct result *out = OUT;
    u32 cs, v, pass, offset, error = 0u;
    out->magic = MAGIC; out->version = 1u; out->state = 1u; out->error = 0u;
    out->bytes_first = out->bytes_second = 0u;
    /* SC read disables IRQ; SC write restores its exact saved state. */
    cs = SC;
    __asm__ volatile ("" ::: "memory");
    out->block_before = SPI[1]; out->config_before = SPI[5];
    if (!read_command(0x9fu, 0u, 3u, &v)) { error = 1u; goto done; }
    out->jedec = v;
    if (v != 0x1660c8u) { error = 2u; goto done; }
    if (!status(&v)) { error = 3u; goto done; }
    out->status_before = v;
    if (v & 3u) { error = 4u; goto done; } /* WIP/WEL must both be clear */
    for (pass = 0u; pass < 2u; ++pass) {
        volatile u8 *dest = pass ? out->second : out->first;
        for (offset = 0u; offset < 256u; offset += 4u) {
            if (!read_command(0x48u, 0x1000u + offset, 4u, &v)) {
                error = 5u; goto done;
            }
            dest[offset] = (u8)v; dest[offset + 1u] = (u8)(v >> 8);
            dest[offset + 2u] = (u8)(v >> 16); dest[offset + 3u] = (u8)(v >> 24);
            if (pass) out->bytes_second = offset + 4u;
            else out->bytes_first = offset + 4u;
        }
    }
    if (!status(&v)) { error = 6u; goto done; }
    out->status_after = v;
    if (out->status_before != v) error = 7u;
done:
    /* Only restore controller configuration if it is idle. A timeout returns
     * an explicit incomplete result; it cannot yield a successful blank record.
     */
    if (idle()) { SPI[5] = out->config_before; SPI[1] = out->block_before; }
    else if (!error) error = 8u;
    out->block_after = SPI[1]; out->config_after = SPI[5];
    if ((out->block_before != out->block_after || out->config_before != out->config_after)
            && !error) error = 9u;
    out->error = error;
    __asm__ volatile ("" ::: "memory");
    SC = cs;
    out->state = error ? 3u : 2u;
    return error;
}
