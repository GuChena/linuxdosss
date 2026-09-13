import queue
import threading
import tkinter as tk
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from test_gui_reply_filter import load_gui_module


class HeldThread:
    def __init__(self, *args, **kwargs):
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive


class BrowserTaskGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.real_thread = threading.Thread
        self.module = load_gui_module()
        self.original_save = self.module.GUI._save_settings
        self.original_load = self.module.GUI._load_settings
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.destroy_root)
        self.stack.enter_context(patch.object(self.module.tk, "Tk", return_value=self.root))
        for method in ("_init_tray", "_check_update", "_save_settings"):
            self.stack.enter_context(patch.object(self.module.GUI, method))
        self.stack.enter_context(patch.object(self.module.GUI, "_load_settings", return_value={}))
        self.stack.enter_context(patch.object(self.module.messagebox, "showinfo"))
        self.stack.enter_context(patch.object(self.module.messagebox, "showerror"))
        self.stack.enter_context(patch.object(self.module.threading, "Thread", side_effect=HeldThread))
        self.gui = self.module.GUI()
        self.gui.simprint_key_var.set("test-key")
        self.gui._finish_simprint_fetch_envs([
            {"uuid": "sim-a", "name": "同名环境", "status": "ready"},
            {"uuid": "sim-b", "name": "同名环境", "status": "ready"},
        ], None)
        self.gui._finish_bitbrowser_fetch([{"id": "bit-a", "name": "窗口 A", "seq": 1}], None)

    def destroy_root(self):
        try:
            for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
                self.root.after_cancel(job)
            self.root.destroy()
        except tk.TclError:
            pass

    def finish_worker(self, outcome):
        self.gui.th.alive = False
        self.gui._done(self.gui.bot, self.gui.task_registry.active_key, outcome)

    def progress_row_values(self, row):
        values = []
        for column in range(5):
            label = self.gui.progress_inner.grid_slaves(row=row, column=column)[0]
            variable = label.cget("textvariable")
            values.append(self.root.getvar(variable) if variable else label.cget("text"))
        return values

    def assert_unknown_info(self):
        self.assertEqual(self.gui.user_label.get(), "用户: -")
        self.assertEqual(self.gui.level_label.get(), "等级: -")
        self.assertEqual(self.gui.next_level_label.get(), "下一级: -")
        self.assertEqual(self.progress_row_values(1), ["-"] * 5)
        self.assertEqual(len(self.gui.progress_inner.winfo_children()), 10)

    def refresh_layout(self, container):
        # Hidden test windows need their geometry managers invoked explicitly.
        for child in container.winfo_children():
            if child.winfo_manager() == "grid":
                child.grid_configure(sticky=child.grid_info()["sticky"])
            elif child.winfo_manager() == "pack":
                child.pack_configure(fill=child.pack_info()["fill"])
        self.root.update_idletasks()
        for child in container.winfo_children():
            self.refresh_layout(child)

    def test_table_columns_align_and_scrolling_keeps_the_header_visible(self):
        self.gui.browser_backend_var.set("simprint")
        self.gui._on_backend_toggle()
        self.gui._finish_simprint_fetch_envs([
            {"uuid": f"env-{i}", "name": f"{i + 1} - Linux.do 环境名称", "status": "ready"}
            for i in range(40)
        ], None)
        self.gui._complete_browser_task("simprint", "env-1")
        self.root.update()
        self.refresh_layout(self.root)
        table = self.gui.simprint_task_table
        for column in range(5):
            header = table.header.grid_bbox(column, 0)
            body = table.body.grid_bbox(column, 0)
            self.assertEqual((header[0], header[2]), (body[0], body[2]))
        for button in table.rows["env-0"]["buttons"].values():
            self.assertEqual(button.winfo_width(), button.winfo_reqwidth())
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), button.master.winfo_width())
        table._update_scroll_region()
        before = table.canvas.yview()[0]
        header_y = table.header.winfo_y()
        table._scroll(4)
        self.assertGreater(table.canvas.yview()[0], before)
        self.assertEqual(table.header.winfo_y(), header_y)
        table.select("env-39", notify=True)
        table.see("env-39")
        self.assertEqual(self.gui.simprint_env_var.get(), "env-39")

    def test_start_buttons_and_programmatic_calls_share_the_same_reservation(self):
        self.assertTrue(self.gui._start_browser_task("simprint", "sim-a"))
        owner = self.gui.bot
        self.assertFalse(self.gui._start_browser_task("simprint", "sim-b"))
        self.assertFalse(self.gui._start_browser_task("bitbrowser", "bit-a"))
        self.assertFalse(self.gui._start())
        self.assertIs(self.gui.bot, owner)
        for table in self.gui.browser_tables.values():
            for row in table.rows.values():
                self.assertEqual(row["buttons"]["start"].cget("state"), tk.DISABLED)

    def test_duplicate_names_start_the_selected_id_and_snapshot_configuration(self):
        self.assertEqual(len(self.gui.simprint_task_table.rows), 2)
        self.gui._start_browser_task("simprint", "sim-b")
        self.assertEqual(self.gui.bot.cfg["simprint_env_uuid"], "sim-b")
        original_port = self.gui.bot.cfg["simprint_api_port"]
        self.gui.simprint_task_table.select("sim-a", notify=True)
        self.gui.simprint_port_var.set("9001")
        self.gui.cfg["simprint_api_port"] = 9001
        self.gui.cats[0]["e"] = False
        self.assertEqual(self.gui.bot.cfg["simprint_env_uuid"], "sim-b")
        self.assertEqual(self.gui.bot.cfg["simprint_api_port"], original_port)
        self.assertTrue(self.gui.bot.cats[0]["e"])

    def test_manual_completion_is_deferred_until_thread_has_exited(self):
        self.gui._start_browser_task("simprint", "sim-a")
        key = self.gui.task_registry.active_key
        self.gui._complete_browser_task("simprint", "sim-a")
        self.assertTrue(self.gui.bot._stop_requested.is_set())
        self.gui._done(self.gui.bot, key, self.module.STOPPED)
        self.assertTrue(self.gui.task_registry.busy)
        self.assertEqual(self.gui.task_registry.get(key)["completed_at"], "")
        self.assertFalse(self.gui._start_browser_task("bitbrowser", "bit-a"))
        self.finish_worker(self.module.STOPPED)
        self.assertEqual(self.gui.task_registry.get(key)["status"], self.module.COMPLETED)
        self.assertTrue(self.gui.task_registry.get(key)["completed_at"])
        self.assertFalse(self.gui.task_registry.busy)

    def test_stopping_and_failure_do_not_write_a_completion_time(self):
        for outcome in (self.module.STOPPED, self.module.ERROR):
            with self.subTest(outcome=outcome):
                self.gui._start_browser_task("simprint", "sim-a")
                key = self.gui.task_registry.active_key
                if outcome == self.module.STOPPED:
                    self.gui._stop()
                self.finish_worker(outcome)
                self.assertEqual(self.gui.task_registry.get(key)["status"], outcome)
                self.assertEqual(self.gui.task_registry.get(key)["completed_at"], "")

    def test_final_progress_shows_latest_site_values_and_session_differences(self):
        for environment_id, initial_count, complete in (
            ("sim-a", 1000, False), ("sim-b", 2000, True),
        ):
            with self.subTest(environment=environment_id, complete=complete):
                self.assertTrue(self.gui._start_browser_task("simprint", environment_id))
                initial_requirements = [
                    {"name": "浏览帖子", "current": f"{initial_count:,}", "required": "6,000"},
                    {"name": "浏览话题", "current": "50", "required": "200"},
                    {"name": "给出的赞", "current": "10", "required": "30"},
                ]
                self.gui._update_info({"requirements": initial_requirements})
                self.root.update()
                self.gui._update_progress({"posts_read": 20, "topic": 5, "like": 3})
                self.root.update()
                self.assertEqual(
                    self.gui.req_labels["浏览帖子"]["current_var"].get(),
                    str(initial_count + 20),
                )

                if complete:
                    self.gui._complete_browser_task("simprint", environment_id)
                else:
                    self.gui._stop()
                self.gui._update_info({"requirements": [
                    {"name": "浏览帖子", "current": f"{initial_count + 12:,}", "required": "6,000"},
                    {"name": "浏览话题", "current": "48", "required": "200"},
                    {"name": "给出的赞", "current": "10", "required": "30"},
                ]}, is_final=True)
                self.finish_worker(self.module.STOPPED)
                self.root.update()

                expected = {
                    "浏览帖子": (f"{initial_count:,}", f"{initial_count + 12:,}", "+12"),
                    "浏览话题": ("50", "48", "-2"),
                    "给出的赞": ("10", "10", "+0"),
                }
                for name, values in expected.items():
                    labels = self.gui.req_labels[name]
                    self.assertEqual((
                        labels["initial"], labels["current_var"].get(), labels["added_var"].get(),
                    ), values)
                self.assertEqual(self.gui.initial_requirements, initial_requirements)
                self.assertFalse(self.gui.task_registry.busy)

    def test_starting_another_environment_or_restarting_clears_previous_info(self):
        self.assert_unknown_info()
        for environment_id in ("sim-a", "sim-b", "sim-b"):
            with self.subTest(environment=environment_id):
                self.assertTrue(self.gui._start_browser_task("simprint", environment_id))
                self.assert_unknown_info()
                self.gui._update_progress({"posts_read": 20})
                self.root.update()
                self.assert_unknown_info()
                self.gui._update_info({
                    "username": environment_id, "level": "1", "nextLevel": "2",
                    "requirements": [
                        {"name": "浏览帖子", "current": "100", "required": "600"},
                    ],
                })
                self.root.update()
                self.assertEqual(self.gui.user_label.get(), "用户: " + environment_id)
                self.assertEqual(self.progress_row_values(1), ["浏览帖子", "100", "100", "600", "+0"])
                self.finish_worker(self.module.STOPPED)

    def test_missing_info_clears_old_values_and_does_not_resume_estimates(self):
        for is_final in (False, True):
            for missing in (None, {}, {"username": "", "level": None, "nextLevel": " ", "requirements": []}):
                with self.subTest(is_final=is_final, missing=missing):
                    self.gui._update_info({
                        "username": "old-user", "level": "1", "nextLevel": "2",
                        "requirements": [
                            {"name": "浏览帖子", "current": "100", "required": "600"},
                        ],
                    })
                    self.gui._update_progress({"posts_read": 20})
                    self.root.update()
                    self.assertEqual(self.progress_row_values(1)[2], "120")
                    self.gui._update_info(missing, is_final=is_final)
                    self.root.update()
                    self.assert_unknown_info()
                    self.gui._update_progress({"posts_read": 30})
                    self.root.update()
                    self.assert_unknown_info()

    def test_partial_info_clears_missing_fields_and_preserves_zero_values(self):
        self.assertTrue(self.gui._start_browser_task("simprint", "sim-a"))
        self.gui._update_info({"username": "old-user", "level": "2", "nextLevel": "3"})
        self.root.update()
        self.gui.bot.pg = Mock()
        self.gui.bot.pg.run_js.return_value = {
            "username": "new-user", "level": 0,
            "requirements": [
                {"name": "浏览帖子", "current": 0},
                {"name": "给出的赞", "current": " ", "required": "30"},
            ],
        }
        with patch.object(self.module.time, "sleep"):
            self.gui.bot.get_level_info()
        self.root.update()
        self.assertEqual(self.gui.user_label.get(), "用户: new-user")
        self.assertEqual(self.gui.level_label.get(), "等级: 0级")
        self.assertEqual(self.gui.next_level_label.get(), "下一级: -")
        self.assertEqual(self.progress_row_values(1), ["浏览帖子", "0", "0", "-", "+0"])
        self.assertEqual(self.progress_row_values(2), ["给出的赞", "-", "-", "30", "-"])
        self.gui._update_progress({"posts_read": 2, "like": 3})
        self.root.update()
        self.assertEqual(self.progress_row_values(1), ["浏览帖子", "0", "2", "-", "+2"])
        self.assertEqual(self.progress_row_values(2), ["给出的赞", "-", "-", "30", "-"])

    def test_final_fetch_clears_missing_metrics_and_fields(self):
        self.gui._update_info({
            "requirements": [
                {"name": "浏览帖子", "current": "100", "required": "600"},
                {"name": "给出的赞", "current": "10", "required": "30"},
            ],
        })
        self.gui._update_progress({"posts_read": 20, "like": 3})
        self.root.update()
        self.gui._update_info({
            "requirements": [
                {"name": "浏览帖子", "current": None, "required": "6,000"},
                {"name": "回复帖子", "current": "3", "required": "5"},
            ],
        }, is_final=True)
        self.gui._update_progress({"posts_read": 30, "like": 4, "reply": 2})
        self.root.update()
        self.assertEqual(self.progress_row_values(1), ["浏览帖子", "100", "-", "6,000", "-"])
        self.assertEqual(self.progress_row_values(2), ["给出的赞", "10", "-", "-", "-"])
        self.assertEqual(self.progress_row_values(3), ["回复帖子", "-", "3", "5", "-"])

    def test_final_only_fetch_leaves_initial_value_and_difference_unknown(self):
        self.gui._update_info(None)
        self.root.update()
        self.gui._update_info({
            "username": "current-user", "level": "1", "nextLevel": "2",
            "requirements": [
                {"name": "浏览帖子", "current": "112", "required": "600"},
            ],
        }, is_final=True)
        self.root.update()
        self.assertEqual(self.gui.user_label.get(), "用户: current-user")
        self.assertEqual(self.progress_row_values(1), ["浏览帖子", "-", "112", "600", "-"])
        self.gui._update_progress({"posts_read": 20})
        self.root.update()
        self.assertEqual(self.progress_row_values(1), ["浏览帖子", "-", "112", "600", "-"])

    def test_refresh_keeps_the_running_row_and_its_stop_action(self):
        self.gui._start_browser_task("simprint", "sim-a")
        self.gui._finish_simprint_fetch_envs([
            {"uuid": "sim-b", "name": "改名后的环境", "status": "ready"}
        ], None)
        self.assertIn("sim-a", self.gui.simprint_task_table.rows)
        self.assertEqual(
            self.gui.simprint_task_table.rows["sim-a"]["buttons"]["stop"].cget("state"),
            tk.NORMAL,
        )
        self.assertEqual(self.gui.bot.cfg["simprint_env_uuid"], "sim-a")

    def test_saved_entries_preserve_duplicate_names_and_completion_records(self):
        self.gui._complete_browser_task("simprint", "sim-b")
        saved = self.gui._collect_settings()
        self.assertEqual(len(saved["simprint_env_entries"]), 2)
        self.gui._finish_simprint_fetch_envs([], None)
        self.gui._apply_settings(saved)
        self.assertEqual(len(self.gui.simprint_task_table.rows), 2)
        record = self.gui.task_registry.get(self.module.task_key("simprint", "sim-b"))
        self.assertEqual(record["status"], self.module.COMPLETED)
        self.assertEqual(self.gui.simprint_task_table.rows["sim-b"]["cells"][3].cget("text"), record["completed_at"])

    def test_old_list_settings_are_migrated_and_keep_selection(self):
        self.gui._apply_settings({
            "simprint_env_options": {"旧环境 [ready]": "legacy-id"},
            "simprint_env_selection": "旧环境 [ready]",
            "simprint_env_uuid": "legacy-id",
        })
        self.assertEqual(self.gui.browser_entries["simprint"], [{"id": "legacy-id", "name": "旧环境"}])
        self.assertEqual(self.gui.simprint_task_table.selected_id, "legacy-id")

    def test_completion_records_are_written_and_read_from_settings_file(self):
        self.gui._complete_browser_task("simprint", "sim-b")
        key = self.module.task_key("simprint", "sim-b")
        with TemporaryDirectory(prefix="linuxdo-task-test-") as directory:
            path = Path(directory) / "settings.json"
            with patch.object(self.module, "get_settings_path", return_value=str(path)):
                self.original_save(self.gui)
                restored = self.original_load(self.gui)
            self.assertEqual(restored["browser_tasks"][key], self.gui.task_registry.get(key))
            self.assertEqual(len(restored["simprint_env_entries"]), 2)
            self.assertFalse(Path(str(path) + ".tmp").exists())

    def test_thread_creation_failure_releases_reservation_as_error(self):
        with patch.object(self.module.threading, "Thread", side_effect=RuntimeError("no thread")):
            self.assertFalse(self.gui._start_browser_task("simprint", "sim-a"))
        self.assertFalse(self.gui.task_registry.busy)
        record = self.gui.task_registry.get(self.module.task_key("simprint", "sim-a"))
        self.assertEqual(record["status"], self.module.ERROR)
        self.assertEqual(record["completed_at"], "")

    def test_close_waits_for_active_worker_cleanup(self):
        self.gui._start_browser_task("simprint", "sim-a")
        self.gui._close()
        self.assertTrue(self.gui._closing)
        self.assertTrue(self.gui.task_registry.busy)
        self.assertTrue(self.root.winfo_exists())
        self.finish_worker(self.module.STOPPED)
        self.assertFalse(self.gui.task_registry.busy)
        try:
            exists = self.root.winfo_exists()
        except tk.TclError:
            exists = False
        self.assertFalse(exists)

    def test_row_buttons_start_stop_and_complete_their_own_environment(self):
        table = self.gui.simprint_task_table
        table.rows["sim-b"]["buttons"]["start"].invoke()
        self.assertEqual(self.gui.bot.cfg["simprint_env_uuid"], "sim-b")
        table.rows["sim-a"]["buttons"]["start"].invoke()
        self.assertEqual(self.gui.bot.cfg["simprint_env_uuid"], "sim-b")
        table.rows["sim-b"]["buttons"]["stop"].invoke()
        self.assertEqual(
            self.gui.task_registry.get(self.module.task_key("simprint", "sim-b"))["status"],
            self.module.STOPPING,
        )
        self.finish_worker(self.module.STOPPED)
        table.rows["sim-b"]["buttons"]["complete"].invoke()
        self.assertEqual(
            self.gui.task_registry.get(self.module.task_key("simprint", "sim-b"))["status"],
            self.module.COMPLETED,
        )

    def test_real_worker_must_exit_before_another_backend_can_start(self):
        pending = queue.Queue()
        bots = []
        workers = []
        module = self.module

        class ControlledBot:
            def __init__(self, cfg, cats, *args, **kwargs):
                self.cfg = cfg
                self.cats = cats
                self.stats = module.new_stats()
                self.started = threading.Event()
                self.release = threading.Event()
                self.stop_requested = threading.Event()
                bots.append(self)

            def run_session(self):
                self.started.set()
                self.release.wait(3)
                return module.STOPPED

            def stop(self):
                self.stop_requested.set()

        def schedule(delay, callback=None, *args):
            if callback:
                pending.put(lambda: callback(*args))
            return "queued"

        def make_thread(*args, **kwargs):
            worker = self.real_thread(*args, **kwargs)
            workers.append(worker)
            return worker

        def drain():
            while not pending.empty():
                pending.get_nowait()()

        with patch.object(module, "Bot", ControlledBot), \
             patch.object(module.threading, "Thread", side_effect=make_thread), \
             patch.object(self.root, "after", side_effect=schedule):
            try:
                self.assertTrue(self.gui._start_browser_task("simprint", "sim-a"))
                self.assertTrue(bots[0].started.wait(1))
                self.assertFalse(self.gui._start_browser_task("bitbrowser", "bit-a"))
                self.gui._stop()
                self.assertTrue(bots[0].stop_requested.is_set())
                self.assertFalse(self.gui._start_browser_task("simprint", "sim-b"))
                self.assertEqual(len(bots), 1)
                bots[0].release.set()
                workers[0].join(2)
                self.assertFalse(workers[0].is_alive())
                drain()
                self.assertFalse(self.gui.task_registry.busy)
                self.assertTrue(self.gui._start_browser_task("bitbrowser", "bit-a"))
                self.assertTrue(bots[1].started.wait(1))
                bots[1].release.set()
                workers[1].join(2)
                drain()
                self.assertFalse(self.gui.task_registry.busy)
            finally:
                for bot in bots:
                    bot.release.set()
                for worker in workers:
                    worker.join(2)


if __name__ == "__main__":
    unittest.main()
