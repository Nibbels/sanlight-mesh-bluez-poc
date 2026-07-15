import unittest
from datetime import datetime, timedelta, timezone

from sanlight_mesh.gateway_protocol import GatewayCommand
from sanlight_mesh.gateway_queue import GatewayCommandQueue


class GatewayQueueTest(unittest.TestCase):
    def command(self, command_id, value, target="0003"):
        now = datetime(2026, 7, 15, tzinfo=timezone.utc)
        return GatewayCommand(
            command_id=command_id,
            action="set-max",
            target=target,
            value=value,
            confirmed=False,
            created_at=now,
            expires_at=now + timedelta(seconds=30),
        )

    def test_coalesces_latest_same_node_without_reordering_other_nodes(self):
        queue = GatewayCommandQueue(10)
        first = self.command("a", 40)
        second = self.command("b", 45)
        other = self.command("c", 55, "0002")
        queue.put(first)
        queue.put(second)
        queue.put(other)
        taken = queue.get()
        selected, superseded = queue.coalesce_set_max(
            taken, wait_seconds=1, sleep=lambda seconds: None
        )
        self.assertEqual(selected.command_id, "b")
        self.assertEqual([(item.command.command_id, item.replacement_id) for item in superseded], [("a", "b")])
        self.assertEqual(queue.get().command_id, "c")

    def test_duplicate_pending_id_is_not_enqueued(self):
        queue = GatewayCommandQueue(2)
        command = self.command("same", 48)
        self.assertTrue(queue.put(command))
        self.assertFalse(queue.put(command))
