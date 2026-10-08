"""Offline checks for the settings UI server.

Run: .venv/bin/python -m unittest discover -s tools -p 'test_*.py'
"""
import json
from pathlib import Path
import re
import unittest

from tracker_ui import CATALOG, build_frame, parse_status

# Shape copied from a real ts + getapn capture (firmware/live/after-reboot-status.raw).
TS_REPLY = """sms_ts_handle.
ver:R36S_RFHZ_V34_V1.0_2024.09.28_16.06.24;
ID:1403167417;
ip_url:47.106.163.223;
port:8888;
center:;
sos1:;
upload:600S;
language:0;
zone:8.00;
NET:OK(100);
AT RETURN:tsver:R36S_RFHZ_V34_V1.0_2024.09.28_16.06.24;
gps:0,snr:0,agps:0,fix:0,is_gprs_attached:1,gsm:1,sim:1,signal:100,bat:100,pwon_count:17,upload=600
get_apn_handle.apn:sme.vodafone.iot.UserName=,Password=,mccmnc=90128
AT RETURN:getapn.
"""


class FrameTests(unittest.TestCase):
    def test_wire_format_matches_verified_commands(self):
        self.assertEqual(build_frame('ts'), b'AT:ts#\r')
        self.assertEqual(build_frame(' apn,sme.vodafone.iot,,,90128 '), b'AT:apn,sme.vodafone.iot,,,90128#\r')

    def test_rejects_framing_injection(self):
        for bad in ['', 'ts#reset', 'ts\rreset', 'a\nb', 'x\x00', 'ts;reset', 'é']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_frame(bad)

    def test_rejects_flash_and_identity_keywords(self):
        for bad in ['flashread', 'cleanfnv', 'imei,123456789012345', 'UPGRADE,http://x', 'delfile,a']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_frame(bad)

    def test_firmware_buffer_limit(self):
        build_frame('x' * 185)
        with self.assertRaises(ValueError):
            build_frame('x' * 186)


class StatusTests(unittest.TestCase):
    def test_parses_ts_and_getapn(self):
        v = parse_status(TS_REPLY)
        self.assertEqual(v['ver'], 'R36S_RFHZ_V34_V1.0_2024.09.28_16.06.24')
        self.assertEqual(v['ip_url'], '47.106.163.223')
        self.assertEqual(v['port'], '8888')
        self.assertEqual(v['center'], '')
        self.assertEqual(v['upload'], '600S')
        self.assertEqual(v['zone'], '8.00')
        self.assertEqual((v['apn'], v['apn_user'], v['apn_mccmnc']), ('sme.vodafone.iot', '', '90128'))


def load_catalog():
    return json.loads(Path(CATALOG).read_text())


def settings_by_id(cat):
    return {s['id']: s for group in cat['groups'] for s in group['settings']}


def preset_command(setting, values):
    """Same substitution the page uses, after the field checks."""
    fields = {f['name']: f for f in setting.get('fields', [])}
    if set(values) != set(fields):
        raise AssertionError(f'{setting["id"]} values {sorted(values)} != fields {sorted(fields)}')
    for name, value in values.items():
        if re.search(r'[,#;]', value):
            raise AssertionError(f'{name} contains a frame delimiter')
        field = fields[name]
        if value == '':
            if not field.get('optional'):
                raise AssertionError(f'{name} is required')
        elif field.get('type') == 'number':
            if not (value.isdigit() and field['min'] <= int(value) <= field['max']):
                raise AssertionError(f'{name}={value} is outside {field["min"]}..{field["max"]}')
        elif 'pattern' in field and re.fullmatch(field['pattern'], value) is None:
            raise AssertionError(f'{name}={value} does not match {field["pattern"]}')
    command = setting['command']
    for name, value in values.items():
        command = command.replace('{' + name + '}', value)
    if '{' in command:
        raise AssertionError(f'unfilled command {command}')
    return command


class CatalogTests(unittest.TestCase):
    def test_every_catalog_command_is_sendable_and_known(self):
        cat = load_catalog()
        keywords = set(cat['keywords'].split())
        for group in cat['groups']:
            for s in group['settings']:
                with self.subTest(setting=s['id']):
                    keyword = s['command'].split(',')[0]
                    self.assertIn(keyword, keywords, 'keyword not in this firmware')
                    names = re.findall(r'\{(\w+)\}', s['command'])
                    self.assertEqual(names, [f['name'] for f in s.get('fields', [])])
                    # Fill with a value of the right shape; the frame must pass server checks.
                    build_frame(re.sub(r'\{\w+\}', '1', s['command']))

    def test_presets_are_named_setups_the_page_can_apply(self):
        cat = load_catalog()
        known = settings_by_id(cat)
        ids = [p['id'] for p in cat['presets']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('vodafone-sme', ids)
        for preset in cat['presets']:
            self.assertTrue(preset['label'] and preset['confirm'] and preset['steps'])
            for step in preset['steps']:
                with self.subTest(preset=preset['id'], setting=step['setting']):
                    build_frame(preset_command(known[step['setting']], step['values']))
        vodafone = next(p for p in cat['presets'] if p['id'] == 'vodafone-sme')
        self.assertEqual(
            [preset_command(known[s['setting']], s['values']) for s in vodafone['steps']],
            ['apn,sme.vodafone.iot,,,90128', 'ip,47.106.163.223,8888'])
        self.assertTrue(known['apn'].get('reboot'))


if __name__ == '__main__':
    unittest.main()
