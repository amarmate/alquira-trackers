#!/bin/bash
# Build the livestock tracker app in the existing rda-usb-builder container.
# The work dir must contain sdk/, runtime/ and tracker/ (these sources).
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
objects=()
for src in tracker/tracker_main.c tracker/tracker_store.c tracker/tracker_motion.c \
           tracker/tracker_gps.c tracker/tracker_upload.c; do
  obj="build/$(basename "$src" .c).o"
  "$cc" "${flags[@]}" -std=gnu99 -D__BUFSIZ__=512 -D__FILENAME_MAX__=256 -DSOC_RDA8955=1 \
      -Itracker -Isdk/include -Isdk/include/ril -c "$src" -o "$obj"
  objects+=("$obj")
done
"$cc" "${flags[@]}" -nostartfiles -nostdlib -nodefaultlibs \
    -Wl,--gc-sections,--relax,-Map,build/tracker.map -T build/linkerscript.ld \
    "${objects[@]}" -Lsdk/lib/rda8955 -Lruntime -lrda_logicrom -lc -lgcc -lm -o build/tracker.elf
"$toolchain/bin/mips-elf-objcopy" -O binary build/tracker.elf build/tracker.raw.bin
"$toolchain/bin/mips-elf-size" build/tracker.elf
"$toolchain/bin/mips-elf-nm" -u build/tracker.elf
