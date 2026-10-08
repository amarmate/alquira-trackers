"""Offline checks for firmware buffer limits and false-positive acknowledgements.

Run: .venv/bin/python -m unittest discover -s tools -p 'test_*.py'
"""
from types import SimpleNamespace
import unittest

from rda_config import acknowledged, build_command


def args(command='set-apn', **overrides):
    values = dict(command=command, apn='sme.vodafone.iot', plmn='90128',
                  host='47.106.163.223', port=8888)
    values.update(overrides)
    return SimpleNamespace(**values)


class ConfigTests(unittest.TestCase):
    def test_verified_wire_format(self):
        self.assertEqual(build_command(args()), b'AT:apn,sme.vodafone.iot,,,90128#\r')
        self.assertEqual(build_command(args('set-server')), b'AT:ip,47.106.163.223,8888#\r')
        self.assertEqual(build_command(args('status')), b'AT:ts#\r')

    def test_firmware_apn_buffer_boundary(self):
        build_command(args(apn='a' * 31))
        with self.assertRaises(ValueError):
            build_command(args(apn='a' * 32))

    def test_no_delimiter_injection_or_invalid_network(self):
        for bad in ['', 'x,other', 'x#AT:reset', 'x\r', 'x\n', 'x\x00']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_command(args(apn=bad))
        for bad in ['268', '9012800', '90128#', '９０１２８']:
            with self.subTest(plmn=bad), self.assertRaises(ValueError):
                build_command(args(plmn=bad))
        for host, port in [('x#', 8888), ('x', 0), ('x', 65536)]:
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                build_command(args('set-server', host=host, port=port))

    def test_gpio_test_only_drives_led_pins(self):
        self.assertEqual(build_command(args('gpio-test', pin=28, level=1)), b'AT:gpiotest,28,1#\r')
        self.assertEqual(build_command(args('gpio-test', pin=4, level=0)), b'AT:gpiotest,4,0#\r')
        # 32 is the GPS power pin and 0 a UART line: both in the firmware's range, both refused.
        for pin, level in [(32, 1), (0, 1), (None, 1), (28, 2), (28, None)]:
            with self.subTest(pin=pin, level=level), self.assertRaises(ValueError):
                build_command(args('gpio-test', pin=pin, level=level))
        self.assertTrue(acknowledged(args('gpio-test', pin=28, level=1), b'AT RETURN:gpiotest.\n'))
        self.assertFalse(acknowledged(args('gpio-test', pin=28, level=1), b'AT RETURN:ts\n'))

    def test_apn_ack_requires_matching_values_and_completion(self):
        echo = b'set_APN_data.p_APN_name:sme.vodafone.iot.p_UserName:.p_PassWd:.P_UserData:90128.\n'
        ack = b'AT RETURN:apn.\n'
        self.assertFalse(acknowledged(args(), echo))
        self.assertFalse(acknowledged(args(), ack))
        self.assertTrue(acknowledged(args(), echo + ack))
        self.assertFalse(acknowledged(args(plmn='26801'), echo + ack))

    def test_server_ack_requires_actual_setting(self):
        response = b'set_url_port.url:47.106.163.223;port:8888.size:102.\nAT RETURN:ip.\n'
        self.assertTrue(acknowledged(args('set-server'), response))
        self.assertFalse(acknowledged(args('set-server', port=8889), response))


if __name__ == '__main__':
    unittest.main()
