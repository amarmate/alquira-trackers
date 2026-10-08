"""Read the V24's pad-function and GPIO registers once, to check docs/v24-pin-map.md.

Word reads only, through the vendor RDA USB monitor (1e04:0900): the 37 pad
registers, GPIO direction and level, and the accelerometer type in RAM. No write,
reset or retry. The GPIO set, clear and interrupt registers are never read.
Defaults to printing the plan. --read requires a new output file in firmware/live.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, read_block
from rda_recovery_snapshot import read_word

IOMUX_FIRST = 0x01A2A04C    # pad_SDMMC_CLK_cfg; the pads before it are the memory bus
GPIO = 0x01A03000
GPIO_WORDS = (('gpio_oen_val_l', 0x00), ('gpio_val_l', 0x0C),
              ('gpio_oen_val_h', 0x38), ('gpio_val_h', 0x44))
ACCEL_TYPE = 0x82239EB8     # 1 MC3413, 2 MC3416, 3 SC7A20, 4 QMA6100P; 0 = no driver matched yet
FACTORY = 0x3FE000          # holds the IMEI, so it tells one unit from another

# One tuple per pad register, in register order. The index is the SEL field and
# index 0 is the pad's own name; '' is a value the header does not define.
# Source: SDK regs/8955/include/iomux.h.
PADS = (
    ('SDMMC_CLK', 'GPIO_8', 'SPI1_CLK', 'I2C1_SCL'),
    ('SDMMC_CMD', 'GPIO_9', 'SPI1_CS_0', 'I2C1_SDA'),
    ('SDMMC_DATA_0', 'GPIO_10', 'SPI1_CS_1'),
    ('SDMMC_DATA_1', 'GPIO_11', 'SPI1_DI_0'),
    ('SDMMC_DATA_2', 'GPIO_12', 'SPI1_DI_1'),
    ('SDMMC_DATA_3', 'GPIO_13'),
    ('LCD_RSTB', 'GPIO_14', 'DAI_RST', 'I2S_BCK'),
    ('SPI_LCD_CS', 'GPIO_15', 'DAI_CLK', 'I2S_LRCK'),
    ('SPI_LCD_SCK', 'GPIO_16', 'DAI_DI', 'I2S_DI'),
    ('SPI_LCD_DIO', 'GPIO_17', 'DAI_DO', 'I2S_DO'),
    ('SPI_LCD_SDC', 'GPIO_18'),
    ('CAM_PWDN', 'GPIO_19', 'I2C2_SCL'),
    ('CAM_RSTB', 'GPIO_20', 'I2C2_SDA'),
    ('CAM_CLK', 'GPIO_21'),
    ('SPI_CAM_SCK', 'GPIO_22'),
    ('SPI_CAM_DI_0', 'GPIO_23', 'SPI_CAM_DI_1'),
    ('SPI_CAM_DI_1', 'GPIO_24', 'SPI_CAM_DI_0', 'SPI_CAM_SSN'),
    ('GPIO_0', 'UART1_RXD', 'SPI2_CLK', '', 'SEGOUT_0', 'DBG_DO_0'),
    ('GPIO_1', 'UART1_TXD', 'SPI2_CS_0', '', 'SEGOUT_1', 'DBG_DO_1'),
    ('GPIO_2', 'UART1_CTS', 'SPI2_CS_1', 'PWL_1', 'SEGOUT_2', 'DBG_DO_2'),
    ('GPIO_3', 'UART1_RTS', 'SPI2_DI_0', 'LPSCO_1', 'SEGOUT_3', 'DBG_DO_3'),
    ('GPIO_4', 'UART2_RXD', 'SPI2_DI_1', 'LPG', 'SEGOUT_4', 'DBG_DO_4'),
    ('GPIO_5', 'UART2_TXD', 'LCD_TE', 'PWT', 'SEGOUT_5', 'DBG_DO_5'),
    ('GPIO_6', 'UART2_CTS', 'I2C3_SCL', 'TCO_3', 'SEGOUT_6', 'DBG_DO_6'),
    ('GPIO_7', 'UART2_RTS', 'I2C3_SDA', 'TCO_4', 'SEGOUT_7', 'DBG_DO_7'),
    ('KEYIN_0', 'GPIO_25', '', '', 'SEGOUT_8', 'DBG_DO_8'),
    ('KEYIN_1', 'GPIO_26', '', '', 'SEGOUT_9', 'DBG_DO_9'),
    ('KEYIN_2', 'GPIO_27', '', '', 'SEGOUT_10', 'DBG_DO_10'),
    ('KEYIN_3', 'GPIO_28', '', '', 'SEGOUT_11', 'DBG_DO_11'),
    ('KEYIN_4', 'GPIO_29', '', '', 'SEGOUT_12', 'DBG_DO_12'),
    ('KEYOUT_0', 'GPIO_30', '', '', 'SEGOUT_13', 'DBG_DO_13'),
    ('KEYOUT_1', 'GPIO_31', '', '', 'SEGOUT_14', 'DBG_DO_14'),
    ('KEYOUT_2', 'GPIO_32', '', '', 'SEGOUT_15', 'DBG_DO_15'),
    ('KEYOUT_3', 'GPIO_33', '', '', 'SEGOUT_16', 'DBG_CLK'),
    ('KEYOUT_4', 'GPIO_34', '', '', 'SEGOUT_17', 'HST_CLK'),
    ('HST_RXD', 'GPIO_35'),
    ('HST_TXD', 'GPIO_36'),
)
# Bit positions are the same in every pad register.
FLAGS = ((28, 'oen_frc'), (24, 'out_frc'), (20, 'out_reg'), (17, 'oen_reg'),
         (16, 'pull_frc'), (9, 'pull_up'), (8, 'pull_dn'))


def describe(funcs, cfg, oen, val):
    """One table line for a pad: its selected function, flags, and GPIO state if it is a GPIO."""
    sel = cfg & 0xF
    name = funcs[sel] if sel < len(funcs) and funcs[sel] else f'function {sel}?'
    notes = [flag for bit, flag in FLAGS if cfg >> bit & 1]
    gpio = re.fullmatch(r'GPIO_(\d+)', name)
    if gpio:
        n = int(gpio.group(1))
        # gpio_oen_val: 1 = input, 0 = output (SDK gpio.h).
        notes.append('input' if oen >> n & 1 else 'output')
        notes.append(f'level {val >> n & 1}')
    return f'{funcs[0]:13} 0x{cfg:08x}  {name:12} {", ".join(notes)}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(f'Read plan: 1 KiB factory block (unit check); {len(PADS)} pad words, '
          f'{len(GPIO_WORDS)} GPIO words, 1 RAM word. No writes.', flush=True)
    if not args.read:
        return
    root = Path(__file__).resolve().parents[1]
    if args.output is None or not args.output.resolve().is_relative_to(root / 'firmware/live'):
        parser.error('New --output file must be inside firmware/live')
    with args.output.open('x') as log:
        def emit(**data):
            line = json.dumps(data, sort_keys=True)
            log.write(line + '\n')
            log.flush()
            print(line, flush=True)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        devices = [d for d in usb.core.find(find_all=True, backend=backend)
                   if (d.idVendor, d.idProduct) in [(0x1e04, 0x0900), (0x1782, 0x3d00)]]
        if len(devices) != 1 or devices[0].idVendor != 0x1e04:
            raise RuntimeError('Expected exactly one debug-mode tracker (1e04:0900)')
        dev = devices[0]
        interface = dev.get_active_configuration()[(0, 0)]
        if usb.util.get_string(dev, interface.iInterface) != 'RDA Usb':
            raise RuntimeError('Expected RDA Usb interface')
        try:
            stale = dev.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise RuntimeError('Queued data; refusing requests')
        backup = (root / 'firmware/backup/v24_1403167417_flash.bin').read_bytes()
        if read_block(dev, 0x88000000 + FACTORY) != backup[FACTORY:FACTORY + 1024]:
            raise RuntimeError('Factory block differs from the 417 backup: not unit 1403167417')
        emit(event='unit', id='1403167417')
        cfgs = []
        for index, funcs in enumerate(PADS):
            address = IOMUX_FIRST + 4 * index
            cfgs.append(read_word(dev, address))
            emit(event='word', name=f'pad_{funcs[0]}_cfg', address=hex(address), value=hex(cfgs[-1]))
        gpio = {}
        for name, offset in GPIO_WORDS:
            gpio[name] = read_word(dev, GPIO + offset)
            emit(event='word', name=name, address=hex(GPIO + offset), value=hex(gpio[name]))
        accel = read_word(dev, ACCEL_TYPE)
        emit(event='word', name='accel_type', address=hex(ACCEL_TYPE), value=hex(accel))
    oen = gpio['gpio_oen_val_l'] | gpio['gpio_oen_val_h'] << 32
    val = gpio['gpio_val_l'] | gpio['gpio_val_h'] << 32
    print()
    for funcs, cfg in zip(PADS, cfgs):
        print(describe(funcs, cfg, oen, val))


if __name__ == '__main__':
    status = 0
    try:
        main()
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)
