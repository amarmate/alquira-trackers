// Before analysis: make Ghidra's memory look like the running firmware's.
// The flash image alone hides three things. Flash is read-only, and until Ghidra knows
// that the decompiler will not show string and pool constants. Boot copies part of the
// image to RAM and SRAM, where the rest of the firmware calls it. And about 1 MiB of
// code is stored LZMA-compressed and unpacked to RAM at boot.
// Every bound below is read from the firmware's own boot code (design spec, section 11).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.io.ByteArrayInputStream;
import org.tukaani.xz.LZMAInputStream;

public class SetupMemory extends GhidraScript {
    private static final long FLASH = 0x88000000L;
    private Memory mem;

    @Override
    public void run() throws Exception {
        mem = currentProgram.getMemory();
        mem.getBlock(toAddr(FLASH)).setPermissions(true, false, true);

        // Copied by the boot loaders (the first stage's pool at flash 0xdc4, the second
        // stage's loops in the function at flash 0x3ebc). The second stage then
        // write-protects the code ranges; that is how text is told from data here.
        // Text is read-only so pool constants show; data must stay writable, or the
        // decompiler would fold the initial value of every global into the code.
        //     name              run address  flash    length   write  execute
        copied("boot_sram",      0x81c00680L, 0x029d0, 0x01450, true,  true);  // first stage's own section
        copied("sram_irq",       0x81c00280L, 0x042e0, 0x001b0, false, true);
        copied("sram_boot",      0x81c01ad0L, 0x04490, 0x00430, false, true);
        copied("sram_boot_data", 0x81c01f00L, 0x048c0, 0x00080, true,  false);
        copied("sram_text",      0x81c01f80L, 0x04940, 0x062e0, false, true);
        copied("sram_data",      0x81c08260L, 0x0ac20, 0x00780, true,  false);
        copied("ram_boot",       0x82000100L, 0x105b0, 0x00d60, false, true);
        copied("ram_text",       0x82000e60L, 0x11310, 0x13f30, false, true);
        copied("ram_data",       0x82014d90L, 0x25240, 0x08850, true,  false);

        // Unpacked at boot by the three loaders at flash 0x1620a4, 0x162108 and 0x162170,
        // which name source, destination and length. In the public SDK's linker script
        // these sections take only .text and .rodata, so they are read-only.
        //       name            run address  flash     packed   unpacked
        unpacked("ram_overlay1", 0x8201d5e0L, 0x2d7860, 0x1ea72, 0x32c80);
        unpacked("ram_overlay2", 0x82050260L, 0x2f6300, 0x5dc52, 0x9a8e0);
        unpacked("ram_overlay3", 0x820eab40L, 0x353f80, 0x0d88e, 0x17340);

        // Flash code ends at 0x238704. What follows is data the code points at: not
        // executable, or Ghidra finds "functions" in string tables. The store is
        // rewritten at run time (file system, settings, calibration, factory block), so
        // it must not read as constant.
        data("flash_data",  0x238720, 0x1298e0, false);  // strings, tables, UI images, packed code
        data("flash_store", 0x362000, 0x09e000, true);

        // No bytes, but a block gives globals and call targets a stable label.
        //    name          start        length     execute
        blank("sram_low",   0x81c00000L, 0x000280,  false);
        blank("sram_gap",   0x81c00430L, 0x000250,  false);
        blank("sram_bss",   0x81c089e0L, 0x007620,  false);
        blank("rom",        0x81e00000L, 0x010000,  true).setWrite(false);  // named from the ROM map
        blank("ram_low",    0x82000000L, 0x000100,  false);
        blank("ram_bss",    0x82101e80L, 0x2fe180,  false);  // to the end of 4 MiB
        blank("sysreg",     0xa1a00000L, 0x040000,  false).setVolatile(true);

        for (MemoryBlock block : mem.getBlocks()) {
            // What is left of the flash block after carving: the code that runs in place.
            if (block.getName().startsWith("flash") && block.isExecute()) {
                block.setName(String.format("flash_%06x", block.getStart().getOffset() - FLASH));
            }
            println("V24: block " + block.getName() + " " + block.getStart() + "-" + block.getEnd()
                    + " " + (block.isWrite() ? "w" : "-") + (block.isExecute() ? "x" : "-")
                    + (block.isInitialized() ? "" : " (no bytes)"));
        }
        println("V24: SetupMemory done");
    }

    // A section the firmware runs from RAM. The bytes are loaded at the run address and
    // stay visible in flash as "img_<name>", not executable: analysed there they would
    // become a second, wrong copy of every function.
    private void copied(String name, long run, long flashOffset, long length,
                        boolean write, boolean execute) throws Exception {
        byte[] bytes = new byte[(int) length];
        mem.getBytes(toAddr(FLASH + flashOffset), bytes);
        MemoryBlock image = carve(FLASH + flashOffset, length);
        image.setName("img_" + name);
        image.setPermissions(true, false, false);
        MemoryBlock block = mem.createInitializedBlock(name, toAddr(run),
                new ByteArrayInputStream(bytes), length, monitor, false);
        block.setPermissions(true, write, execute);
    }

    private void data(String name, long flashOffset, long length, boolean write) throws Exception {
        MemoryBlock block = carve(FLASH + flashOffset, length);
        block.setName(name);
        block.setPermissions(true, write, false);
    }

    // The packed bytes stay where they are, inside flash_data: nothing runs from there.
    private void unpacked(String name, long run, long flashOffset, int packedLength,
                          int length) throws Exception {
        byte[] packed = new byte[packedLength];
        mem.getBytes(toAddr(FLASH + flashOffset), packed);
        byte[] bytes;
        try (LZMAInputStream lzma = new LZMAInputStream(new ByteArrayInputStream(packed))) {
            bytes = lzma.readAllBytes();
        }
        if (bytes.length != length) {
            throw new IllegalStateException(name + ": unpacked " + bytes.length + " bytes, expected " + length);
        }
        MemoryBlock block = mem.createInitializedBlock(name, toAddr(run),
                new ByteArrayInputStream(bytes), length, monitor, false);
        block.setPermissions(true, false, true);
    }

    // Split the flash block so that [start, start + length) is a block of its own.
    private MemoryBlock carve(long start, long length) throws Exception {
        MemoryBlock block = mem.getBlock(toAddr(start));
        if (block.getStart().getOffset() != start) {
            mem.split(block, toAddr(start));
            block = mem.getBlock(toAddr(start));
        }
        if (block.getEnd().getOffset() != start + length - 1) {
            mem.split(block, toAddr(start + length));
            block = mem.getBlock(toAddr(start));
        }
        return block;
    }

    private MemoryBlock blank(String name, long start, long length, boolean execute) throws Exception {
        MemoryBlock block = mem.createUninitializedBlock(name, toAddr(start), length, false);
        block.setPermissions(true, true, execute);
        return block;
    }
}
