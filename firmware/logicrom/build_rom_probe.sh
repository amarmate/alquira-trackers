#!/bin/bash
set -euo pipefail
export LD_LIBRARY_PATH=/work/csdtk/lib
cc=/work/csdtk/bin/mips-elf-gcc
cd /work/probe
mkdir -p build
flags=(-EL -Os -Wall -Wextra -Werror -march=xcpu -mtune=xcpu -mno-mips16 -msoft-float
       -mno-abicalls -fno-pic -G0 -ffreestanding -fno-builtin -fno-stack-protector
       -ffixed-t3 -ffixed-t4 -ffixed-t5 -ffixed-t6 -ffixed-t7
       -ffixed-s2 -ffixed-s3 -ffixed-s4 -ffixed-s5 -ffixed-s6 -ffixed-s7 -ffixed-fp
       -ffunction-sections -fdata-sections)
"$cc" --version
for stage in return jedec jedec-fc security-fc; do
  case "$stage" in
    return)      sources=(rom_return_probe.S);                   defines=();;
    jedec)       sources=(rom_jedec_probe.c);                    defines=();;
    jedec-fc)    sources=(rom_jedec_entry.S rom_jedec_probe.c);   defines=(-DJEDEC_VIA_EXTENDED);;
    security-fc) sources=(rom_security_entry.S rom_security_probe.c); defines=();;
  esac
  objects=()
  for source in "${sources[@]}"; do
    object="build/$stage-$(basename "$source" | sed 's/\.[cS]$//').o"
    "$cc" "${flags[@]}" "${defines[@]}" -c "$source" -o "$object"
    objects+=("$object")
  done
  "$cc" -EL -mno-mips16 -mno-abicalls -fno-pic -G0 -nostartfiles -nostdlib -nodefaultlibs \
    -Wl,--gc-sections,-Map,"build/$stage.map" -T rom_probe.ld "${objects[@]}" -o "build/$stage.elf"
  /work/csdtk/bin/mips-elf-objcopy -O binary "build/$stage.elf" "build/$stage.bin"
  /work/csdtk/bin/mips-elf-objdump -d "build/$stage.elf" > "build/$stage.dis"
  /work/csdtk/bin/mips-elf-readelf -h -l "build/$stage.elf" > "build/$stage.elf.txt"
  /work/csdtk/bin/mips-elf-nm -u "build/$stage.elf"
  wc -c "build/$stage.bin"
done
