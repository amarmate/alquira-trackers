#!/bin/bash
set -euo pipefail
export LD_LIBRARY_PATH=/work/csdtk/lib
cc=/work/csdtk/bin/mips-elf-gcc
cd /work/reader
mkdir -p build
"$cc" --version
"$cc" -EL -Os -Wall -Wextra -Werror -march=xcpu -mtune=xcpu -mno-mips16 -msoft-float \
  -mno-abicalls -fno-pic -G0 -ffreestanding -fno-builtin -fno-stack-protector \
  -ffixed-t3 -ffixed-t4 -ffixed-t5 -ffixed-t6 -ffixed-t7 \
  -ffixed-s2 -ffixed-s3 -ffixed-s4 -ffixed-s5 -ffixed-s6 -ffixed-s7 -ffixed-fp \
  -ffunction-sections -fdata-sections -c security_reader.c -o build/security_reader.o
"$cc" -EL -mno-mips16 -mno-abicalls -fno-pic -G0 -nostartfiles -nostdlib -nodefaultlibs \
  -Wl,--gc-sections,-Map,build/security_reader.map -T security_reader.ld \
  build/security_reader.o -o build/security_reader.elf
/work/csdtk/bin/mips-elf-objcopy -O binary build/security_reader.elf build/security_reader.bin
/work/csdtk/bin/mips-elf-objdump -d build/security_reader.elf > build/security_reader.dis
/work/csdtk/bin/mips-elf-readelf -h -l build/security_reader.elf > build/security_reader.elf.txt
/work/csdtk/bin/mips-elf-nm -u build/security_reader.elf
wc -c build/security_reader.bin
