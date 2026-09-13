import unittest
from unittest.mock import Mock, call, patch

from test_gui_reply_filter import load_gui_module


class BotTaskOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.module = load_gui_module()
        self.bot = self.module.Bot(
            self.module.default_config(), [{"n": "test", "u": "/test", "e": True}],
            Mock(), mode="topics", target_value=3, browse_mode="quick",
            enable_like=False, enable_reply=False, enable_wait=False,
        )
        self.bot.start = Mock(return_value=True)
        self.bot.check_login = Mock(return_value=True)
        self.bot.get_level_info = Mock(return_value=None)
        self.bot.close = Mock()
        self.bot._random_delay = Mock()
        self.bot.pg = Mock()
        self.cleanup_calls = Mock()
        self.cleanup_calls.attach_mock(self.bot.get_level_info, "get_level_info")
        self.cleanup_calls.attach_mock(self.bot.close, "close")

    def test_quantity_target_continues_across_category_rounds(self):
        def browse(category):
            self.bot.stats["topic"] += 1
            return 1
        self.bot.browse_cat = Mock(side_effect=browse)
        self.assertEqual(self.bot.run_session(), self.module.COMPLETED)
        self.assertEqual(self.bot.browse_cat.call_count, 3)
        self.assertEqual(self.cleanup_calls.mock_calls, [
            call.get_level_info(), call.get_level_info(is_final=True), call.close(),
        ])

    def test_time_target_completes_when_elapsed(self):
        current = [1000]
        self.bot.mode = "time"
        self.bot.target_value = 2
        def browse(category):
            current[0] += 120
        self.bot.browse_cat = Mock(side_effect=browse)
        with patch.object(self.module.time, "time", side_effect=lambda: current[0]):
            self.assertEqual(self.bot.run_session(), self.module.COMPLETED)

    def test_stop_before_worker_starts_never_launches_browser(self):
        self.bot.stop()
        self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.bot.start.assert_not_called()
        self.bot.get_level_info.assert_not_called()

    def test_stop_during_browser_start_closes_it_without_logging_in(self):
        def start():
            self.bot.stop()
            return True
        self.bot.start.side_effect = start
        self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.bot.check_login.assert_not_called()
        self.bot.get_level_info.assert_not_called()
        self.bot.close.assert_called_once()

    def test_stop_during_login_closes_without_fetching_progress(self):
        def check_login(**kwargs):
            self.bot.stop()
            return False
        self.bot.check_login.side_effect = check_login
        self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.bot.get_level_info.assert_not_called()
        self.bot.close.assert_called_once()

    def test_login_failure_is_an_error_and_closes_browser(self):
        self.bot.check_login.return_value = False
        self.assertEqual(self.bot.run_session(), self.module.ERROR)
        self.bot.get_level_info.assert_not_called()
        self.bot.close.assert_called_once()

    def test_launch_failure_is_not_a_completion(self):
        self.bot.start.return_value = False
        self.assertEqual(self.bot.run_session(), self.module.ERROR)
        self.assertFalse(self.bot.run)

    def test_manual_stop_refreshes_progress_before_closing(self):
        self.bot.browse_cat = Mock(side_effect=lambda category: self.bot.stop())
        self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.assertTrue(self.bot._stop_requested.is_set())
        self.bot.browse_cat.assert_called_once()
        self.assertEqual(self.cleanup_calls.mock_calls, [
            call.get_level_info(), call.get_level_info(is_final=True), call.close(),
        ])

    def test_stop_refreshes_site_data_and_reports_final_progress(self):
        initial = {
            "username": "test", "level": "1",
            "requirements": [{"name": "已读帖子", "current": "100", "required": "600"}],
        }
        final = {
            "username": "test", "level": "1",
            "requirements": [{"name": "已读帖子", "current": "105", "required": "600"}],
        }
        self.bot.get_level_info.side_effect = (
            lambda is_final=False: self.module.Bot.get_level_info(self.bot, is_final)
        )
        self.bot.pg.run_js.side_effect = [initial, None, final]
        self.bot.update_info = Mock()
        self.cleanup_calls.attach_mock(self.bot.update_info, "update_info")
        self.bot.browse_cat = Mock(side_effect=lambda category: self.bot.stop())
        with patch.object(self.module.time, "sleep"):
            self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.assertEqual(self.cleanup_calls.mock_calls, [
            call.get_level_info(), call.update_info(initial, False),
            call.get_level_info(is_final=True), call.update_info(final, True),
            call.close(),
        ])
        self.bot.pg.run_js.assert_any_call("location.reload(true)")
        self.assertEqual(self.bot.user_info, final)
        self.bot.lg.assert_any_call("  已读帖子: 100 → 105 (+5)")

    def test_failed_final_progress_fetch_still_closes_browser(self):
        self.bot.get_level_info.side_effect = (
            lambda is_final=False: self.module.Bot.get_level_info(self.bot, is_final)
        )
        self.bot.pg.get.side_effect = [None, RuntimeError("site unavailable")]
        self.bot.pg.run_js.return_value = None
        self.bot.browse_cat = Mock(side_effect=lambda category: self.bot.stop())
        with patch.object(self.module.time, "sleep"):
            self.assertEqual(self.bot.run_session(), self.module.STOPPED)
        self.bot.lg.assert_any_call("获取等级失败: site unavailable")
        self.bot.close.assert_called_once()

    def test_missing_level_info_notifies_gui_to_clear_old_values(self):
        for is_final in (False, True):
            for failure in ("empty", "exception"):
                with self.subTest(is_final=is_final, failure=failure):
                    self.bot.user_info = {"username": "old-user"}
                    self.bot.level_requirements = [{"name": "浏览帖子", "current": "100"}]
                    self.bot.update_info = Mock()
                    self.bot.pg.run_js.return_value = None
                    self.bot.pg.get.side_effect = RuntimeError("site unavailable") if failure == "exception" else None
                    with patch.object(self.module.time, "sleep"):
                        result = self.module.Bot.get_level_info(self.bot, is_final=is_final)
                    self.assertIsNone(result)
                    self.bot.update_info.assert_called_once_with(None, is_final)
                    self.assertIsNone(self.bot.user_info)
                    self.assertEqual(self.bot.level_requirements, [])

    def test_browser_is_closed_when_browsing_raises(self):
        self.bot.browse_cat = Mock(side_effect=RuntimeError("browser disconnected"))
        with self.assertRaises(RuntimeError):
            self.bot.run_session()
        self.bot.close.assert_called_once()

    def test_cancelled_bot_does_not_start_new_interactions(self):
        self.bot.pg = Mock()
        self.bot.stop()
        self.assertFalse(self.bot.do_like())
        self.assertFalse(self.bot.do_reply())
        self.bot.pg.run_js.assert_not_called()


if __name__ == "__main__":
    unittest.main()
