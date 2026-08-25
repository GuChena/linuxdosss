import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from linux_do.session_stats import (
    add_read_progress,
    add_topic_progress,
    new_stats,
    progress_added_for_metric,
)


class SessionStatsTests(unittest.TestCase):
    def test_topic_and_post_counters_are_separate(self):
        stats = new_stats()

        add_topic_progress(stats)
        add_read_progress(stats, 4)

        self.assertEqual(stats["topic"], 1)
        self.assertEqual(stats["floors"], 4)
        self.assertEqual(stats["posts_read"], 5)

    def test_invalid_floor_progress_does_not_change_counters(self):
        stats = new_stats()

        self.assertEqual(add_read_progress(stats, "unknown"), 0)
        self.assertEqual(add_read_progress(stats, -2), 0)
        self.assertEqual(stats["floors"], 0)
        self.assertEqual(stats["posts_read"], 0)

    def test_upgrade_metrics_use_specific_counter(self):
        stats = new_stats()
        stats.update({"topic": 2, "posts_read": 7, "floors": 5, "like": 1, "like_reply": 2, "reply": 3})

        self.assertEqual(progress_added_for_metric("浏览话题", stats), 2)
        self.assertEqual(progress_added_for_metric("浏览帖子", stats), 7)
        self.assertEqual(
            progress_added_for_metric("浏览帖子", {"topic": 2, "floors": 5}),
            7,
        )
        self.assertEqual(progress_added_for_metric("给出的赞", stats), 3)
        self.assertEqual(progress_added_for_metric("点赞", stats), 3)
        self.assertEqual(progress_added_for_metric("回复", stats), 3)
        self.assertIsNone(progress_added_for_metric("收到的赞", stats))


if __name__ == "__main__":
    unittest.main()
