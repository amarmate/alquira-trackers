#!/bin/bash
# Run in the existing rda-usb-builder container, with /work/logicrom and /work/csdtk.
set -euo pipefail
toolchain=${V24_TOOLCHAIN:-/work/csdtk}
export LD_LIBRARY_PATH="$toolchain/lib"
cd "${V24_LOGICROM_WORK:-/work/logicrom}"
mkdir -p build
cc="$toolchain/bin/mips-elf-gcc"
flags=(-Os -g -ffunction-sections -fdata-sections -fsigned-char -fno-strict-aliasing
       -Wall -Wextra -Werror -march=xcpu -mtune=xcpu -Wa,-march=xcpu,-mtune=xcpu
       -mips16 -minterlink-mips16 -msoft-float -mexplicit-relocs -mmemcpy -mmips-tfile
       -DEL -EL -G0 -ffixed-t3 -ffixed-t4 -ffixed-t5 -ffixed-t6 -ffixed-t7
       -ffixed-s2 -ffixed-s3 -ffixed-s4 -ffixed-s5 -ffixed-s6 -ffixed-s7 -ffixed-fp)
"$cc" --version
"$cc" -P -x c -E sdk/lib/rda8955/linkerscript.ld -o build/linkerscript.ld
"$cc" "${flags[@]}" -std=gnu99 -D__BUFSIZ__=512 -D__FILENAME_MAX__=256 -DSOC_RDA8955=1 \
    -Isdk/include -Isdk/include/ril -c main.c -o build/main.o
"$cc" "${flags[@]}" -nostartfiles -nostdlib -nodefaultlibs \
    -Wl,--gc-sections,--relax,-Map,build/probe.map -T build/linkerscript.ld \
    build/main.o -Lsdk/lib/rda8955 -Lruntime -lrda_logicrom -lc -lgcc -lm -o build/probe.elf
"$toolchain/bin/mips-elf-objcopy" -O binary build/probe.elf build/probe.raw.bin
"$toolchain/bin/mips-elf-size" build/probe.elf
"$toolchain/bin/mips-elf-readelf" -h -l build/probe.elf
