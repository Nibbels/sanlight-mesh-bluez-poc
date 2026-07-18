import unittest

from sanlight_mesh.constants import (
    SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
    SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
)
from sanlight_mesh.protocol import (
    build_get_combined_daylight_data_pdu,
    build_get_daylight_configuration_pdu,
    decode_daylight_status_pdu,
)


def daylight_parameters(*, configuration_id=7, name="Flower 12/12", values=None):
    points = values or ((0, 0), (360, 20), (390, 100), (1080, 0))
    return (
        configuration_id.to_bytes(4, "little")
        + bytes((len(points),))
        + b"".join(
            minute.to_bytes(2, "little") + bytes((brightness,))
            for minute, brightness in points
        )
        + name.encode("utf-8")
        + b"\x00"
    )


class DaylightProtocolTest(unittest.TestCase):
    def test_read_only_request_pdus(self):
        self.assertEqual(
            build_get_daylight_configuration_pdu(), bytes.fromhex("c38b0a")
        )
        self.assertEqual(
            build_get_combined_daylight_data_pdu(), bytes.fromhex("ce8b0a")
        )

    def test_configuration_status_is_decoded_and_raw_data_is_retained(self):
        pdu = bytes.fromhex("c48b0a") + daylight_parameters()
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
        )

        self.assertTrue(status.parsed)
        self.assertEqual(status.parser_layout, "configuration-v1")
        self.assertEqual(status.raw_pdu, pdu)
        self.assertEqual(status.configuration.configuration_id, 7)
        self.assertEqual(status.configuration.name, "Flower 12/12")
        self.assertEqual(
            [(value.time_in_minutes, value.brightness) for value in status.configuration.values],
            [(0, 0), (360, 20), (390, 100), (1080, 0)],
        )
        document = status.to_document()
        self.assertEqual(document["rawPduHex"], pdu.hex())
        self.assertEqual(document["configuration"]["values"][1]["time"], "06:00")

    def test_combined_status_decodes_hardware_confirmed_prefix(self):
        pdu = bytes.fromhex(
            "cf8b0a"
            "b7be7803"  # lamp clock: 58,244,791 ms
            "2c01"      # live brightness raw: 300 => 30.0%
            "1e"        # MaxBrightness: 30%
            "99367b38"  # configuration id: 947,599,001
            "08"
            "000000"
            "670100"
            "680114"
            "860164"
            "1a0464"
            "380414"
            "390400"
            "a00500"
            "313030252031323a313200"
        )
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
        )

        self.assertTrue(status.parsed)
        self.assertEqual(status.parser_layout, "combined-live-max-prefix-v1")
        self.assertEqual(status.lamp_time_ms, 58_244_791)
        self.assertEqual(status.live_brightness_raw, 300)
        self.assertEqual(status.max_brightness, 30)
        self.assertEqual(status.configuration.configuration_id, 947_599_001)
        self.assertEqual(status.configuration.name, "100% 12:12")
        self.assertEqual(
            [
                (value.time_in_minutes, value.brightness)
                for value in status.configuration.values
            ],
            [
                (0, 0),
                (359, 0),
                (360, 20),
                (390, 100),
                (1050, 100),
                (1080, 20),
                (1081, 0),
                (1440, 0),
            ],
        )
        document = status.to_document()
        self.assertEqual(document["combinedStatus"]["lampClock"], "16:10:44.791")
        self.assertEqual(document["combinedStatus"]["maxBrightness"], 30)

    def test_combined_status_decodes_real_18_hour_light_profile(self):
        pdu = bytes.fromhex(
            "cf8b0a"
            "ed8ab503"  # lamp clock: 62,229,229 ms
            "2c01"      # live brightness raw: 300 => 30.0%
            "1e"        # MaxBrightness: 30%
            "d487a517"  # configuration id: 396,724,180
            "07"
            "000000"
            "680100"
            "690114"
            "860164"
            "820564"
            "9e0514"
            "a00500"
            "3130302520363a313800"
        )
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
        )

        self.assertTrue(status.parsed)
        self.assertEqual(status.parser_layout, "combined-live-max-prefix-v1")
        self.assertEqual(status.configuration.configuration_id, 396_724_180)
        self.assertEqual(status.configuration.name, "100% 6:18")
        self.assertEqual(
            [
                (value.time_in_minutes, value.brightness)
                for value in status.configuration.values
            ],
            [
                (0, 0),
                (360, 0),
                (361, 20),
                (390, 100),
                (1410, 100),
                (1438, 20),
                (1440, 0),
            ],
        )
        document = status.to_document()
        self.assertEqual(document["combinedStatus"]["lampClock"], "17:17:09.229")
        self.assertEqual(document["combinedStatus"]["liveBrightnessRaw"], 300)
        self.assertEqual(document["combinedStatus"]["maxBrightness"], 30)

    def test_combined_status_decodes_real_always_dark_profile(self):
        pdu = bytes.fromhex(
            "cf8b0a"
            "f37eb603"  # lamp clock: 62,291,699 ms
            "0000"      # live brightness raw: 0
            "1e"        # MaxBrightness: 30%
            "cc82b64d"  # configuration id: 1,303,806,668
            "02"
            "000000"
            "a00500"
            "4162736f6c75742044756e6b656c00"
        )
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
        )

        self.assertTrue(status.parsed)
        self.assertEqual(status.parser_layout, "combined-live-max-prefix-v1")
        self.assertEqual(status.configuration.configuration_id, 1_303_806_668)
        self.assertEqual(status.configuration.name, "Absolut Dunkel")
        self.assertEqual(
            [
                (value.time_in_minutes, value.brightness)
                for value in status.configuration.values
            ],
            [(0, 0), (1440, 0)],
        )
        document = status.to_document()
        self.assertEqual(document["combinedStatus"]["lampClock"], "17:18:11.699")
        self.assertEqual(document["combinedStatus"]["liveBrightnessRaw"], 0)
        self.assertEqual(
            document["combinedStatus"]["liveBrightnessPercentEstimate"], 0.0
        )
        self.assertEqual(document["combinedStatus"]["maxBrightness"], 30)

    def test_unconfirmed_combined_layout_remains_raw_only(self):
        pdu = bytes.fromhex("cf8b0a") + daylight_parameters()
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
        )
        self.assertFalse(status.parsed)
        self.assertIn("daylight value count", status.parse_error)

    def test_malformed_status_remains_available_as_raw_only(self):
        pdu = bytes.fromhex("c48b0a") + daylight_parameters(values=((60, 20), (30, 100)))
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
        )
        self.assertFalse(status.parsed)
        self.assertEqual(status.raw_pdu, pdu)
        self.assertIn("not ordered", status.parse_error)
        self.assertEqual(status.to_document()["rawPduHex"], pdu.hex())

    def test_request_and_status_opcodes_must_match(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            decode_daylight_status_pdu(
                bytes.fromhex("cf8b0a") + daylight_parameters(),
                request_opcode=SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
            )

    def test_unknown_trailing_data_is_not_guessed(self):
        pdu = bytes.fromhex("c48b0a") + daylight_parameters() + b"\x01"
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
        )
        self.assertFalse(status.parsed)
        self.assertIn("unsupported trailing length", status.parse_error)


if __name__ == "__main__":
    unittest.main()
