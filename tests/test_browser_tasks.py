import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from linux_do.browser_tasks import (
    TaskRegistry, RUNNING, STOPPING, STOPPED, COMPLETED, ERROR,
    normalize_entries, task_key,
)


class BrowserTaskStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 12, 10, 30, 45)
        self.registry = TaskRegistry(clock=lambda: self.now)
        self.first = task_key("simprint", "a")
        self.second = task_key("bitbrowser", "a")

    def test_only_one_environment_can_start_across_browser_backends(self):
        self.assertTrue(self.registry.begin(self.first))
        self.assertFalse(self.registry.begin(self.second))
        self.assertEqual(self.registry.active_key, self.first)
        self.assertEqual(self.registry.get(self.first)["status"], RUNNING)

    def test_stopping_keeps_the_reservation_until_worker_exit(self):
        self.registry.begin(self.first)
        self.assertTrue(self.registry.request_stop(self.first))
        self.assertEqual(self.registry.get(self.first)["status"], STOPPING)
        self.assertFalse(self.registry.begin(self.second))
        self.registry.finish(self.first, STOPPED)
        self.assertEqual(self.registry.get(self.first)["completed_at"], "")
        self.assertTrue(self.registry.begin(self.second))

    def test_manual_completion_waits_for_worker_exit_before_stamping_time(self):
        self.registry.begin(self.first)
        self.registry.request_stop(self.first, complete=True)
        self.assertEqual(self.registry.get(self.first)["completed_at"], "")
        self.registry.finish(self.first, STOPPED)
        self.assertEqual(self.registry.get(self.first), {
            "status": COMPLETED, "completed_at": "2026-09-12 10:30:45",
        })

    def test_failure_is_not_reported_as_manual_completion(self):
        self.registry.begin(self.first)
        self.registry.request_stop(self.first, complete=True)
        self.registry.finish(self.first, ERROR)
        self.assertEqual(self.registry.get(self.first)["status"], ERROR)
        self.assertEqual(self.registry.get(self.first)["completed_at"], "")

    def test_stale_completion_cannot_release_a_different_worker(self):
        self.registry.begin(self.first)
        self.assertFalse(self.registry.finish(self.second, COMPLETED))
        self.assertTrue(self.registry.busy)
        self.assertEqual(self.registry.active_key, self.first)

    def test_completed_records_survive_restart_but_running_records_do_not(self):
        self.registry.mark_complete(self.first)
        self.registry.begin(self.second)
        restored = TaskRegistry(self.registry.snapshot())
        self.assertFalse(restored.busy)
        self.assertEqual(restored.get(self.first), self.registry.get(self.first))
        self.assertEqual(restored.get(self.second)["status"], STOPPED)
        self.assertTrue(restored.begin(self.second))

    def test_stopped_retry_retains_the_last_successful_completion_time(self):
        self.registry.mark_complete(self.first)
        previous = self.registry.get(self.first)["completed_at"]
        self.registry.begin(self.first)
        self.registry.request_stop(self.first)
        self.registry.finish(self.first, COMPLETED)
        self.assertEqual(self.registry.get(self.first)["status"], STOPPED)
        self.assertEqual(self.registry.get(self.first)["completed_at"], previous)

    def test_manually_completing_an_idle_row_does_not_stop_another_task(self):
        self.registry.begin(self.first)
        self.assertTrue(self.registry.mark_complete(self.second))
        self.assertEqual(self.registry.active_key, self.first)
        self.assertEqual(self.registry.get(self.first)["status"], RUNNING)
        self.assertEqual(self.registry.get(self.second)["status"], COMPLETED)

    def test_unknown_worker_result_is_an_error(self):
        self.registry.begin(self.first)
        self.registry.finish(self.first, None)
        self.assertEqual(self.registry.get(self.first)["status"], ERROR)

    def test_restoration_does_not_replace_live_state(self):
        self.registry.begin(self.first)
        self.registry.restore({})
        self.assertEqual(self.registry.get(self.first)["status"], RUNNING)

    def test_duplicate_names_do_not_merge_environment_ids(self):
        entries = normalize_entries([
            {"id": "a", "name": "同名环境"},
            {"id": "b", "name": "同名环境"},
            {"id": "a", "name": "重复响应"},
        ])
        self.assertEqual([entry["id"] for entry in entries], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
