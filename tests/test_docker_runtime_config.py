import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "docker" / "linux_do_docker.py"


def load_docker_module():
    sys.modules["DrissionPage"] = types.SimpleNamespace(
        ChromiumPage=object,
        ChromiumOptions=object,
    )
    sys.modules.setdefault("schedule", types.SimpleNamespace())
    spec = importlib.util.spec_from_file_location("linux_do_docker_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerRuntimeConfigTests(unittest.TestCase):
    def test_user_env_selects_endless_deep_without_like_or_reply(self):
        module = load_docker_module()
        parser = module.build_parser()
        args = parser.parse_args([])
        env = {
            "LINUXDO_USERNAME": "alice",
            "LINUXDO_PASSWORD": "secret",
            "RUN_MODE": "endless",
            "BROWSE_MODE": "deep",
            "ENABLE_LIKE": "false",
            "ENABLE_REPLY": "false",
            "RUN_ON_START": "true",
            "CONTAINER_NAME": "linuxdo-bot",
            "TZ": "Asia/Shanghai",
            "CHROME_USER_DATA": "/app/chrome-data",
            "MEMORY_LIMIT": "1G",
            "CPU_LIMIT": "1.0",
            "DEBUG": "",
        }

        config = module.load_runtime_config(args, env)

        self.assertEqual(config.username, "alice")
        self.assertEqual(config.password, "secret")
        self.assertEqual(config.run_mode, "endless")
        self.assertEqual(config.browse_mode, "deep")
        self.assertFalse(config.enable_like)
        self.assertFalse(config.enable_reply)
        self.assertEqual(config.like_rate, 0.0)

    def test_parser_defaults_do_not_override_env_schedule_numbers(self):
        module = load_docker_module()
        parser = module.build_parser()
        args = parser.parse_args([])
        env = {
            "LINUXDO_USERNAME": "alice",
            "LINUXDO_PASSWORD": "secret",
            "RUN_MODE": "schedule",
            "RUNS_PER_DAY": "1",
            "TOPICS_MIN": "8",
            "TOPICS_MAX": "18",
            "LIKE_RATE": "0",
        }

        config = module.load_runtime_config(args, env)

        self.assertEqual(config.run_mode, "schedule")
        self.assertEqual(config.runs_per_day, 1)
        self.assertEqual(config.topics_min, 8)
        self.assertEqual(config.topics_max, 18)
        self.assertEqual(config.like_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
