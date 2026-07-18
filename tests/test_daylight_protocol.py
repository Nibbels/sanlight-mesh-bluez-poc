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

    def test_combined_status_accepts_live_prefix_and_suffix_layouts(self):
        live = (38_310_000).to_bytes(4, "little") + (680).to_bytes(2, "little")
        configuration = daylight_parameters(name="Vegetative 18/6")

        for layout, parameters in (
            ("combined-live-prefix-v1", live + configuration),
            ("combined-live-suffix-v1", configuration + live),
        ):
            with self.subTest(layout=layout):
                pdu = bytes.fromhex("cf8b0a") + parameters
                status = decode_daylight_status_pdu(
                    pdu,
                    request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
                )
                self.assertTrue(status.parsed)
                self.assertEqual(status.parser_layout, layout)
                self.assertEqual(status.lamp_time_ms, 38_310_000)
                self.assertEqual(status.live_brightness_raw, 680)
                self.assertEqual(status.configuration.name, "Vegetative 18/6")

    def test_combined_status_accepts_exact_configuration_only_layout(self):
        pdu = bytes.fromhex("cf8b0a") + daylight_parameters()
        status = decode_daylight_status_pdu(
            pdu,
            request_opcode=SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
        )
        self.assertTrue(status.parsed)
        self.assertEqual(status.parser_layout, "combined-configuration-only-v1")

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
