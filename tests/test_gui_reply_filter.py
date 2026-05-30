import importlib.util
import inspect
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "linux_do_gui.py"


def load_gui_module():
    sys.modules["DrissionPage"] = types.SimpleNamespace(
        ChromiumPage=object,
        ChromiumOptions=object,
    )
    spec = importlib.util.spec_from_file_location("linux_do_gui_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuiReplyRangeTests(unittest.TestCase):
    def test_parse_reply_count_range_accepts_blank_max_as_unlimited(self):
        module = load_gui_module()

        reply_min, reply_max = module.parse_reply_count_range("5", "")

        self.assertEqual(reply_min, 5)
        self.assertIsNone(reply_max)

    def test_parse_reply_count_range_falls_back_when_invalid_or_reversed(self):
        module = load_gui_module()

        self.assertEqual(module.parse_reply_count_range("abc", "120"), (0, 120))
        self.assertEqual(module.parse_reply_count_range("80", "20"), (0, 120))

    def test_filter_topics_by_reply_count_is_inclusive_and_preserves_order(self):
        module = load_gui_module()
        topics = [
            {"id": "1", "replyCount": 4},
            {"id": "2", "replyCount": 5},
            {"id": "3", "replyCount": 80},
            {"id": "4", "replyCount": 81},
            {"id": "5", "replyCount": None},
        ]

        filtered = module.filter_topics_by_reply_count(topics, 5, 80)

        self.assertEqual([topic["id"] for topic in filtered], ["2", "3"])

    def test_select_topic_candidates_filters_replies_before_unread_fallback(self):
        module = load_gui_module()
        payload = {
            "unread": [
                {"id": "unread-small", "replyCount": 12},
                {"id": "unread-large", "replyCount": 300},
            ],
            "read": [
                {"id": "read-small", "replyCount": 9},
                {"id": "read-large", "replyCount": 500},
            ],
        }

        candidates = module.select_topic_candidates(payload, 0, 120)

        self.assertEqual(
            [topic["id"] for topic in candidates],
            ["unread-small", "read-small"],
        )

    def test_select_topic_candidates_unread_only_does_not_fallback_to_read(self):
        module = load_gui_module()
        payload = {
            "unread": [{"id": "unread-small", "replyCount": 12}],
            "read": [{"id": "read-small", "replyCount": 9}],
        }

        candidates = module.select_topic_candidates(
            payload, 0, 120, unread_only=True
        )

        self.assertEqual([topic["id"] for topic in candidates], ["unread-small"])

    def test_select_topic_candidates_unread_only_skips_when_no_unread_matches(self):
        module = load_gui_module()
        payload = {
            "unread": [{"id": "unread-large", "replyCount": 300}],
            "read": [{"id": "read-small", "replyCount": 9}],
        }

        candidates = module.select_topic_candidates(
            payload, 0, 120, unread_only=True
        )

        self.assertEqual(candidates, [])

    def test_merge_topic_payloads_deduplicates_by_topic_id_and_preserves_order(self):
        module = load_gui_module()
        first = {
            "unread": [
                {"id": "1", "title": "first unread", "replyCount": 12},
                {"id": "2", "title": "second unread", "replyCount": 15},
            ],
            "read": [{"id": "3", "title": "first read", "replyCount": 20}],
        }
        second = {
            "unread": [
                {"id": "2", "title": "second unread duplicate", "replyCount": 15},
                {"id": "4", "title": "new unread", "replyCount": 22},
            ],
            "read": [{"id": "3", "title": "first read duplicate", "replyCount": 20}],
        }

        merged = module.merge_topic_payloads(first, second)

        self.assertEqual([topic["id"] for topic in merged["unread"]], ["1", "2", "4"])
        self.assertEqual([topic["id"] for topic in merged["read"]], ["3"])
        self.assertEqual([topic["id"] for topic in merged["all"]], ["1", "2", "4", "3"])

    def test_count_topic_candidates_uses_current_reply_filter_and_unread_mode(self):
        module = load_gui_module()
        payload = {
            "unread": [
                {"id": "1", "replyCount": 12},
                {"id": "2", "replyCount": 300},
            ],
            "read": [{"id": "3", "replyCount": 20}],
        }

        count = module.count_topic_candidates(
            payload, 10, 30, unread_only=True
        )

        self.assertEqual(count, 1)

    def test_get_topics_js_reads_only_the_reply_column_next_to_views(self):
        module = load_gui_module()

        script = module.build_get_topics_js()

        self.assertIn("td.num.posts-map.posts", script)
        self.assertNotIn("td.num.posts button", script)
        self.assertNotIn("td.num.posts'", script)
        self.assertNotIn("td.posts button", script)
        self.assertNotIn("td.posts'", script)

    def test_get_topics_js_treats_unparseable_reply_count_as_unknown(self):
        module = load_gui_module()

        script = module.build_get_topics_js()

        self.assertIn("return null;", script)
        self.assertIn("replyCount === null", script)

    def test_get_topics_does_not_click_reply_sort_header(self):
        module = load_gui_module()

        source = inspect.getsource(module.Bot.get_topics)

        self.assertNotIn("clickRepliesSort", source)
        self.assertNotIn("data-sort-order=\"posts\"", source)

    def test_get_topics_can_scroll_list_to_load_more_topics(self):
        module = load_gui_module()

        source = inspect.getsource(module.Bot.get_topics)

        self.assertIn("list_scroll_times", source)
        self.assertIn("window.scrollTo(0, document.body.scrollHeight)", source)


if __name__ == "__main__":
    unittest.main()
