import unittest

from sanlight_mesh.max_brightness_policy import (
    SET_MAX_GROUP_MAX_ATTEMPTS,
    SET_MAX_UNICAST_MAX_ATTEMPTS,
    max_attempts_for_destination,
    set_max_status_rejection_reason,
    unicast_status_rejection_reason,
)


class SetMaxPolicyTest(unittest.TestCase):
    NODES = {0x0002, 0x0003}
    GROUPS = {0xC000, 0xC001}

    def reason(
        self,
        *,
        source=0x0003,
        key_index=0,
        response_destination=0x2800,
        requested_destination=0x0003,
    ):
        return set_max_status_rejection_reason(
            source=source,
            key_index=key_index,
            response_destination=response_destination,
            requested_destination=requested_destination,
            expected_app_index=0,
            sender_unicast=0x2800,
            node_addresses=self.NODES,
            group_addresses=self.GROUPS,
        )

    def test_unicast_retries_once_but_group_does_not(self):
        self.assertEqual(
            max_attempts_for_destination(0x0003, self.NODES),
            SET_MAX_UNICAST_MAX_ATTEMPTS,
        )
        self.assertEqual(
            max_attempts_for_destination(0xC000, self.NODES),
            SET_MAX_GROUP_MAX_ATTEMPTS,
        )

    def test_exact_unicast_status_is_accepted(self):
        self.assertIsNone(self.reason())

    def test_status_from_other_node_is_rejected(self):
        reason = self.reason(source=0x0002)
        self.assertIn("unexpected source", reason)

    def test_wrong_app_key_is_rejected(self):
        reason = self.reason(key_index=1)
        self.assertIn("AppKey", reason)

    def test_wrong_response_destination_is_rejected(self):
        reason = self.reason(response_destination=0x2400)
        self.assertIn("response destination", reason)

    def test_get_max_unicast_status_matching_is_strict(self):
        self.assertIsNone(
            unicast_status_rejection_reason(
                source=0x0003,
                key_index=0,
                response_destination=0x2800,
                requested_destination=0x0003,
                expected_app_index=0,
                sender_unicast=0x2800,
                node_addresses=self.NODES,
            )
        )
        reason = unicast_status_rejection_reason(
            source=0x0002,
            key_index=0,
            response_destination=0x2800,
            requested_destination=0x0003,
            expected_app_index=0,
            sender_unicast=0x2800,
            node_addresses=self.NODES,
        )
        self.assertIn("unexpected source", reason)

    def test_group_status_accepts_only_known_lamp_sources(self):
        self.assertIsNone(
            self.reason(source=0x0002, requested_destination=0xC000)
        )
        reason = self.reason(source=0x2400, requested_destination=0xC000)
        self.assertIn("not a known SANlight lamp", reason)


if __name__ == "__main__":
    unittest.main()
