import unittest

from sanlight_mesh.protocol import (
    build_config_default_ttl_set_pdu,
    build_config_network_transmit_get_pdu,
    build_get_uptime_brightness_pdu,
    build_set_max_brightness_pdu,
    build_set_uptime_pdu,
    build_vendor_model_app_bind_pdu,
    decode_config_network_transmit_status,
    format_milliseconds_as_clock,
    parse_clock_time,
    parse_destination,
    validate_max_brightness,
)


class ProtocolTest(unittest.TestCase):
    def test_max_brightness_boundaries(self):
        self.assertEqual(validate_max_brightness(20), 20)
        self.assertEqual(validate_max_brightness(100), 100)
        for value in (0, 1, 19, 101, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_max_brightness(value)

    def test_max_brightness_pdu_revalidates(self):
        self.assertEqual(build_set_max_brightness_pdu(68), bytes.fromhex("c68b0a44"))
        with self.assertRaises(ValueError):
            build_set_max_brightness_pdu(0)

    def test_validated_vendor_pdus(self):
        self.assertEqual(build_get_uptime_brightness_pdu(), bytes.fromhex("cc8b0a"))
        self.assertEqual(
            build_set_uptime_pdu(38_310_000), bytes.fromhex("ca8b0a70904802")
        )
        self.assertEqual(build_config_network_transmit_get_pdu(), bytes.fromhex("8023"))
        self.assertEqual(build_config_default_ttl_set_pdu(5), bytes.fromhex("800d05"))
        self.assertEqual(
            build_vendor_model_app_bind_pdu(0x2800),
            bytes.fromhex("803d002800008b0a0100"),
        )

    def test_time_helpers(self):
        self.assertEqual(parse_clock_time("10:38:30"), 38_310_000)
        self.assertEqual(format_milliseconds_as_clock(38_310_000), "10:38:30.000")
        for value in ("24:00", "12:60", "12", "xx:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_clock_time(value)

    def test_destination_parser_is_strict(self):
        self.assertEqual(parse_destination("0003"), 3)
        self.assertEqual(parse_destination("0xC000"), 0xC000)
        for value in ("3", "00003", "zzzz"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_destination(value)

    def test_network_transmit_decode(self):
        self.assertEqual(decode_config_network_transmit_status(bytes.fromhex("802500")), (1, 10))
        self.assertEqual(decode_config_network_transmit_status(bytes.fromhex("80252a")), (3, 60))


if __name__ == "__main__":
    unittest.main()
