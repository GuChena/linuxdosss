# GUI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split stable helper logic out of `src/linux_do_gui.py` without changing GUI behavior, browser automation behavior, launcher behavior, or default values.

**Architecture:** Create a focused `src/linux_do/` package and move pure topic logic, static defaults, and platform/resource helpers into separate modules. Keep `src/linux_do_gui.py` as the executable entry point and compatibility surface by importing and re-exporting moved names.

**Tech Stack:** Python 3, unittest, Tkinter, DrissionPage, Pillow, pystray, PyInstaller.

---

## File Structure

- Create `src/linux_do/__init__.py`: package marker and version export.
- Create `src/linux_do/topics.py`: reply-count parsing, topic filtering, payload merging, candidate counting, and topic-list JavaScript builder.
- Create `src/linux_do/config.py`: version metadata, GitHub repository name, category defaults, config defaults, and runtime copy helpers.
- Create `src/linux_do/resources.py`: Linux input method setup, font selection, settings path, icon path, and tray image creation.
- Modify `src/linux_do_gui.py`: import helpers from the package, keep `CATS`, `CFG`, `VERSION`, `GITHUB_REPO`, and topic helper names available at module level, and remove duplicated local helper bodies.
- Create `tests/test_topics.py`: direct tests for pure topic logic without importing DrissionPage or Tkinter.
- Create `tests/test_gui_compatibility.py`: compatibility tests for the old `linux_do_gui.py` top-level topic helper names.
- Create `tests/test_config.py`: direct tests for default config/category copies and metadata.
- Create `tests/test_resources.py`: direct tests for resource helpers without importing Tkinter or DrissionPage.
- Modify `tests/test_gui_reply_filter.py`: keep only GUI/Bot source-level checks that still need `linux_do_gui.py`.

## Task 1: Extract Topic Helpers

**Files:**
- Create: `tests/test_topics.py`
- Create: `src/linux_do/__init__.py`
- Create: `src/linux_do/topics.py`
- No production behavior changes outside the new package in this task.

- [ ] **Step 1: Write the failing direct topic tests**

Create `tests/test_topics.py`:

```python
import sys
import unittest
from pathlib import Path


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from linux_do import topics


class TopicHelperTests(unittest.TestCase):
    def test_parse_reply_count_range_accepts_blank_max_as_unlimited(self):
        reply_min, reply_max = topics.parse_reply_count_range("5", "")

        self.assertEqual(reply_min, 5)
        self.assertIsNone(reply_max)

    def test_parse_reply_count_range_falls_back_when_invalid_or_reversed(self):
        self.assertEqual(topics.parse_reply_count_range("abc", "120"), (0, 120))
        self.assertEqual(topics.parse_reply_count_range("80", "20"), (0, 120))

    def test_filter_topics_by_reply_count_is_inclusive_and_preserves_order(self):
        payload = [
            {"id": "1", "replyCount": 4},
            {"id": "2", "replyCount": 5},
            {"id": "3", "replyCount": 80},
            {"id": "4", "replyCount": 81},
            {"id": "5", "replyCount": None},
        ]

        filtered = topics.filter_topics_by_reply_count(payload, 5, 80)

        self.assertEqual([topic["id"] for topic in filtered], ["2", "3"])

    def test_select_topic_candidates_filters_replies_before_unread_fallback(self):
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

        candidates = topics.select_topic_candidates(payload, 0, 120)

        self.assertEqual(
            [topic["id"] for topic in candidates],
            ["unread-small", "read-small"],
        )

    def test_select_topic_candidates_unread_only_does_not_fallback_to_read(self):
        payload = {
            "unread": [{"id": "unread-small", "replyCount": 12}],
            "read": [{"id": "read-small", "replyCount": 9}],
        }

        candidates = topics.select_topic_candidates(
            payload, 0, 120, unread_only=True
        )

        self.assertEqual([topic["id"] for topic in candidates], ["unread-small"])

    def test_select_topic_candidates_unread_only_skips_when_no_unread_matches(self):
        payload = {
            "unread": [{"id": "unread-large", "replyCount": 300}],
            "read": [{"id": "read-small", "replyCount": 9}],
        }

        candidates = topics.select_topic_candidates(
            payload, 0, 120, unread_only=True
        )

        self.assertEqual(candidates, [])

    def test_merge_topic_payloads_deduplicates_by_topic_id_and_preserves_order(self):
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

        merged = topics.merge_topic_payloads(first, second)

        self.assertEqual([topic["id"] for topic in merged["unread"]], ["1", "2", "4"])
        self.assertEqual([topic["id"] for topic in merged["read"]], ["3"])
        self.assertEqual([topic["id"] for topic in merged["all"]], ["1", "2", "4", "3"])

    def test_count_topic_candidates_uses_current_reply_filter_and_unread_mode(self):
        payload = {
            "unread": [
                {"id": "1", "replyCount": 12},
                {"id": "2", "replyCount": 300},
            ],
            "read": [{"id": "3", "replyCount": 20}],
        }

        count = topics.count_topic_candidates(payload, 10, 30, unread_only=True)

        self.assertEqual(count, 1)

    def test_get_topics_js_reads_only_the_reply_column_next_to_views(self):
        script = topics.build_get_topics_js()

        self.assertIn("td.num.posts-map.posts", script)
        self.assertNotIn("td.num.posts button", script)
        self.assertNotIn("td.num.posts'", script)
        self.assertNotIn("td.posts button", script)
        self.assertNotIn("td.posts'", script)

    def test_get_topics_js_treats_unparseable_reply_count_as_unknown(self):
        script = topics.build_get_topics_js()

        self.assertIn("return null;", script)
        self.assertIn("replyCount === null", script)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the direct topic tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_topics -v
```

Expected: `ModuleNotFoundError: No module named 'linux_do'`.

- [ ] **Step 3: Create the package and topic module**

Create `src/linux_do/__init__.py`:

```python
"""Core modules for the Linux.do GUI helper."""
```

Create `src/linux_do/topics.py` by moving the exact helper implementations from `src/linux_do_gui.py:244-411`:

```python
def parse_reply_count_range(min_text, max_text, default_min=0, default_max=120):
    """Parse inclusive reply-count bounds from GUI entry text."""

    def parse_bound(value, allow_blank=False):
        text = "" if value is None else str(value).strip()
        if text == "":
            return None if allow_blank else default_min
        count = int(text.replace(",", ""))
        if count < 0:
            raise ValueError("reply count cannot be negative")
        return count

    try:
        reply_min = parse_bound(min_text)
        reply_max = parse_bound(max_text, allow_blank=True)
        if reply_max is not None and reply_min > reply_max:
            raise ValueError("reply count min cannot exceed max")
        return reply_min, reply_max
    except Exception:
        return default_min, default_max


def filter_topics_by_reply_count(topics, reply_min=0, reply_max=120):
    """Keep topics whose replyCount is inside the inclusive range."""
    filtered = []
    for topic in topics or []:
        reply_count = topic.get("replyCount")
        if reply_count is None:
            continue
        try:
            reply_count = int(reply_count)
        except (TypeError, ValueError):
            continue
        if reply_count < reply_min:
            continue
        if reply_max is not None and reply_count > reply_max:
            continue
        filtered.append(topic)
    return filtered


def select_topic_candidates(topics_payload, reply_min=0, reply_max=120, unread_only=False):
    """Filter by reply count, then keep existing unread-first fallback behavior."""
    unread = filter_topics_by_reply_count(
        (topics_payload or {}).get("unread", []), reply_min, reply_max
    )
    read = filter_topics_by_reply_count(
        (topics_payload or {}).get("read", []), reply_min, reply_max
    )

    if unread_only:
        return unread

    if unread:
        if len(unread) < 3 and read:
            return unread + read[:3]
        return unread
    return read


def _topic_key(topic):
    return str(topic.get("id") or topic.get("url") or topic.get("title") or "")


def merge_topic_payloads(existing, incoming):
    """Merge topic payloads from repeated list scans, preserving first-seen order."""
    merged = {"unread": [], "read": [], "all": []}
    seen = set()

    for payload in (existing or {}, incoming or {}):
        for bucket in ("unread", "read"):
            for topic in payload.get(bucket, []) or []:
                key = _topic_key(topic)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged[bucket].append(topic)

    merged["all"] = merged["unread"] + merged["read"]
    return merged


def count_topic_candidates(topics_payload, reply_min=0, reply_max=120, unread_only=False):
    return len(
        select_topic_candidates(
            topics_payload, reply_min, reply_max, unread_only=unread_only
        )
    )


def build_get_topics_js():
    """Build JS that reads topics and the list-page reply column."""
    return """
        function getTopics() {
            function parseReplyCount(text) {
                const normalized = String(text || '').trim().replace(/,/g, '');
                const wanMatch = normalized.match(/([0-9]+(?:[.][0-9]+)?)\\s*万/);
                if (wanMatch) {
                    return Math.round(parseFloat(wanMatch[1]) * 10000);
                }
                const kMatch = normalized.match(/([0-9]+(?:[.][0-9]+)?)\\s*[kK]/);
                if (kMatch) {
                    return Math.round(parseFloat(kMatch[1]) * 1000);
                }
                const numMatch = normalized.match(/[0-9]+/);
                return numMatch ? parseInt(numMatch[0], 10) : null;
            }

            function getReplyCount(row) {
                const replyNode = row.querySelector(
                    'td.num.posts-map.posts button, td.num.posts-map.posts'
                );
                if (!replyNode) {
                    return null;
                }
                return parseReplyCount(replyNode.textContent);
            }

            const rows = document.querySelectorAll('tr.topic-list-item');
            const unreadTopics = [];  // 未读话题（带小蓝点）
            const readTopics = [];    // 已读话题（无小蓝点）

            rows.forEach(row => {
                const link = row.querySelector('a.title.raw-link.raw-topic-link, a.title');
                if (link) {
                    const href = link.getAttribute('href');
                    const title = link.textContent.trim();
                    const topicId = row.getAttribute('data-topic-id');
                    const replyCount = getReplyCount(row);

                    // 跳过置顶帖和无法识别回复数的话题。
                    if (replyCount === null) {
                        return;
                    }

                    if (href && title && !row.classList.contains('pinned')) {
                        // 检查是否有小蓝点（未读标记）
                        const newTopicBadge = row.querySelector('.badge.badge-notification.new-topic');

                        const topicData = {
                            url: href,
                            title: title.substring(0, 50),
                            id: topicId,
                            isUnread: !!newTopicBadge,  // 是否未读
                            replyCount: replyCount
                        };

                        if (newTopicBadge) {
                            unreadTopics.push(topicData);
                        } else {
                            readTopics.push(topicData);
                        }
                    }
                }
            });

            return {
                unread: unreadTopics,
                read: readTopics,
                all: [...unreadTopics, ...readTopics]
            };
        }
        return getTopics();
        """
```

- [ ] **Step 4: Run the direct topic tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_topics -v
```

Expected: all `TopicHelperTests` pass.

- [ ] **Step 5: Commit the extracted topic module**

Run:

```powershell
git add src/linux_do/__init__.py src/linux_do/topics.py tests/test_topics.py
git commit -m "refactor: extract topic helpers"
```

## Task 2: Preserve GUI Topic Compatibility

**Files:**
- Create: `tests/test_gui_compatibility.py`
- Modify: `src/linux_do_gui.py`
- Modify: `tests/test_gui_reply_filter.py`

- [ ] **Step 1: Write the failing compatibility test**

Create `tests/test_gui_compatibility.py`:

```python
import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
MODULE_PATH = SRC_PATH / "linux_do_gui.py"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from linux_do import topics


def load_gui_module():
    sys.modules["DrissionPage"] = types.SimpleNamespace(
        ChromiumPage=object,
        ChromiumOptions=object,
    )
    spec = importlib.util.spec_from_file_location("linux_do_gui_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuiCompatibilityTests(unittest.TestCase):
    def test_topic_helpers_are_reexported_from_the_new_module(self):
        module = load_gui_module()

        self.assertIs(module.parse_reply_count_range, topics.parse_reply_count_range)
        self.assertIs(module.filter_topics_by_reply_count, topics.filter_topics_by_reply_count)
        self.assertIs(module.select_topic_candidates, topics.select_topic_candidates)
        self.assertIs(module.merge_topic_payloads, topics.merge_topic_payloads)
        self.assertIs(module.count_topic_candidates, topics.count_topic_candidates)
        self.assertIs(module.build_get_topics_js, topics.build_get_topics_js)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the compatibility test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui_compatibility -v
```

Expected: `AssertionError` because `src/linux_do_gui.py` still defines separate local topic helper functions.

- [ ] **Step 3: Import topic helpers in `src/linux_do_gui.py` and delete local duplicates**

Add this import block after the Tkinter imports in `src/linux_do_gui.py`:

```python
from linux_do.topics import (
    build_get_topics_js,
    count_topic_candidates,
    filter_topics_by_reply_count,
    merge_topic_payloads,
    parse_reply_count_range,
    select_topic_candidates,
)
```

Delete the duplicated local definitions from `src/linux_do_gui.py`:

```text
def parse_reply_count_range(...)
def filter_topics_by_reply_count(...)
def select_topic_candidates(...)
def _topic_key(...)
def merge_topic_payloads(...)
def count_topic_candidates(...)
def build_get_topics_js(...)
```

Do not change any call sites in `Bot`; the imported names keep the same names.

- [ ] **Step 4: Trim `tests/test_gui_reply_filter.py` to source-level GUI checks**

Replace `tests/test_gui_reply_filter.py` with:

```python
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


class GuiTopicFlowTests(unittest.TestCase):
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
```

- [ ] **Step 5: Run topic, compatibility, and GUI source tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_topics tests.test_gui_compatibility tests.test_gui_reply_filter -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit GUI topic compatibility**

Run:

```powershell
git add src/linux_do_gui.py tests/test_gui_compatibility.py tests/test_gui_reply_filter.py
git commit -m "refactor: import topic helpers in gui"
```

## Task 3: Extract Static Config Defaults

**Files:**
- Create: `tests/test_config.py`
- Create: `src/linux_do/config.py`
- Modify: `src/linux_do/__init__.py`
- Modify: `src/linux_do_gui.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
import sys
import unittest
from pathlib import Path


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from linux_do.config import (
    DEFAULT_CATEGORIES,
    DEFAULT_CONFIG,
    GITHUB_REPO,
    VERSION,
    default_categories,
    default_config,
)


class ConfigTests(unittest.TestCase):
    def test_metadata_matches_current_release_values(self):
        self.assertEqual(VERSION, "8.5.0")
        self.assertEqual(GITHUB_REPO, "icysaintdx/linuxdosss")

    def test_category_defaults_preserve_order_and_enabled_state(self):
        self.assertEqual(len(DEFAULT_CATEGORIES), 16)
        self.assertEqual(DEFAULT_CATEGORIES[0], {"n": "开发调优", "u": "/c/develop/4", "e": True})
        self.assertEqual(DEFAULT_CATEGORIES[-1], {"n": "运营反馈", "u": "/c/feedback/2", "e": False})

    def test_default_categories_returns_independent_runtime_copies(self):
        first = default_categories()
        second = default_categories()

        first[0]["e"] = False

        self.assertTrue(second[0]["e"])
        self.assertTrue(DEFAULT_CATEGORIES[0]["e"])

    def test_default_config_preserves_existing_values(self):
        cfg = default_config()

        self.assertEqual(cfg["proxy"], "127.0.0.1:7897")
        self.assertEqual(cfg["base"], "https://linux.do")
        self.assertEqual(cfg["connect"], "https://connect.linux.do")
        self.assertEqual(cfg["browser_backend"], "builtin")
        self.assertEqual(cfg["bit_api_port"], 54345)
        self.assertEqual(cfg["reply_count_min"], 0)
        self.assertEqual(cfg["reply_count_max"], 120)
        self.assertTrue(cfg["unread_only"])
        self.assertGreater(len(cfg["tpl"]), 50)

    def test_default_config_returns_independent_runtime_copies(self):
        first = default_config()
        second = default_config()

        first["proxy"] = ""
        first["tpl"].append("temporary")

        self.assertEqual(second["proxy"], "127.0.0.1:7897")
        self.assertNotIn("temporary", second["tpl"])
        self.assertEqual(DEFAULT_CONFIG["proxy"], "127.0.0.1:7897")
        self.assertNotIn("temporary", DEFAULT_CONFIG["tpl"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the config tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_config -v
```

Expected: `ModuleNotFoundError: No module named 'linux_do.config'`.

- [ ] **Step 3: Create `src/linux_do/config.py`**

Create the module with this structure:

```python
from copy import deepcopy


VERSION = "8.5.0"
GITHUB_REPO = "icysaintdx/linuxdosss"

DEFAULT_CATEGORIES = [
    {"n": "开发调优", "u": "/c/develop/4", "e": True},
    {"n": "国产替代", "u": "/c/domestic/98", "e": True},
    {"n": "资源荟萃", "u": "/c/resource/14", "e": True},
    {"n": "网盘资源", "u": "/c/resource/cloud-asset/94", "e": True},
    {"n": "文档共建", "u": "/c/wiki/42", "e": True},
    {"n": "积分乐园", "u": "/c/credit/106", "e": False},
    {"n": "非我莫属", "u": "/c/job/27", "e": True},
    {"n": "读书成诗", "u": "/c/reading/32", "e": True},
    {"n": "扬帆起航", "u": "/c/startup/46", "e": False},
    {"n": "前沿快讯", "u": "/c/news/34", "e": True},
    {"n": "网络记忆", "u": "/c/feeds/92", "e": True},
    {"n": "福利羊毛", "u": "/c/welfare/36", "e": True},
    {"n": "搞七捻三", "u": "/c/gossip/11", "e": True},
    {"n": "社区孵化", "u": "/c/incubator/102", "e": False},
    {"n": "虫洞广场", "u": "/c/square/110", "e": True},
    {"n": "运营反馈", "u": "/c/feedback/2", "e": False},
]

DEFAULT_CONFIG = {
    "proxy": "127.0.0.1:7897",
    "base": "https://linux.do",
    "connect": "https://connect.linux.do",
    "browser_backend": "builtin",
    "bit_api_port": 54345,
    "bit_window_id": "",
    "like_rate": 0.3,
    "reply_rate": 0.05,
    "like_reply_rate": 0.15,
    "reply_count_min": 0,
    "reply_count_max": 120,
    "unread_only": True,
    "list_scroll_times": 3,
    "topic_candidate_target": 8,
    "scroll_time": 3,
    "wait_min": 1,
    "wait_max": 3,
    "tpl": [
        "感谢分享！学习了",
        "感谢楼主的分享",
        "感谢分享，很有帮助",
        "感谢大佬的分享",
        "感谢楼主无私分享",
        "感谢分享，收藏学习",
        "感谢楼主，学到了",
        "感谢分享，受益匪浅",
        "学习了，谢谢楼主！",
        "学到了新知识，感谢",
        "涨知识了，谢谢分享",
        "学习学习，感谢大佬",
        "又学到了，感谢楼主",
        "学习一下，感谢分享",
        "认真学习中，感谢",
        "好好学习天天向上",
        "支持一下，感谢分享",
        "支持楼主，继续加油",
        "必须支持，感谢分享",
        "大力支持，感谢楼主",
        "支持支持，学习了",
        "强烈支持，感谢分享",
        "好文章，收藏了",
        "收藏了，感谢分享",
        "先收藏，慢慢学习",
        "收藏学习，感谢楼主",
        "马克一下，感谢分享",
        "mark一下，以后学习",
        "先马后看，感谢分享",
        "不错不错，学习了",
        "写得很好，感谢分享",
        "内容很棒，感谢楼主",
        "干货满满，感谢分享",
        "质量很高，感谢楼主",
        "很有价值，感谢分享",
        "非常实用，感谢楼主",
        "很有帮助，感谢分享",
        "前排围观，感谢分享",
        "前排学习，感谢楼主",
        "前排支持，感谢分享",
        "前排关注，学习了",
        "前排占座，感谢分享",
        "谢谢佬，学习了",
        "感谢佬的分享",
        "佬太强了，学习了",
        "跟着佬学习一下",
        "佬就是佬，感谢分享",
        "大佬牛逼，学习了",
        "膜拜大佬，感谢分享",
        "路过学习，感谢分享",
        "围观学习，感谢楼主",
        "来学习一下，感谢",
        "看看学习，感谢分享",
        "顶一下，感谢分享",
        "顶顶顶，感谢楼主",
        "帮顶一下，感谢分享",
        "好帖必顶，感谢楼主",
        "精华帖子，感谢分享",
        "优质内容，感谢楼主",
        "实用干货，感谢分享",
        "很有意思，感谢楼主",
        "长见识了，感谢分享",
        "开眼界了，感谢楼主",
        "受教了，感谢分享",
        "茅塞顿开，感谢楼主",
    ],
}


def default_categories():
    return deepcopy(DEFAULT_CATEGORIES)


def default_config():
    return deepcopy(DEFAULT_CONFIG)
```

Update `src/linux_do/__init__.py`:

```python
"""Core modules for the Linux.do GUI helper."""

from linux_do.config import VERSION

__all__ = ["VERSION"]
```

- [ ] **Step 4: Wire config defaults into `src/linux_do_gui.py`**

Add imports:

```python
from linux_do.config import GITHUB_REPO, VERSION, default_categories, default_config
```

Replace the old module-level literals:

```python
CATS = default_categories()
CFG = default_config()
```

Delete the old `VERSION`, `GITHUB_REPO`, `CATS`, and `CFG` literal blocks from `src/linux_do_gui.py`.

- [ ] **Step 5: Run config and full topic/GUI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_config tests.test_topics tests.test_gui_compatibility tests.test_gui_reply_filter -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit config extraction**

Run:

```powershell
git add src/linux_do/config.py src/linux_do/__init__.py src/linux_do_gui.py tests/test_config.py
git commit -m "refactor: extract config defaults"
```

## Task 4: Extract Resource And Platform Helpers

**Files:**
- Create: `tests/test_resources.py`
- Create: `src/linux_do/resources.py`
- Modify: `src/linux_do_gui.py`

- [ ] **Step 1: Write the failing resource tests**

Create `tests/test_resources.py`:

```python
import os
import sys
import unittest
from pathlib import Path


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from linux_do.resources import (
    configure_linux_input_method,
    get_font_names,
    get_icon_path,
    get_settings_path,
)


class ResourceTests(unittest.TestCase):
    def test_get_font_names_matches_supported_platforms(self):
        self.assertEqual(get_font_names("Darwin"), ("PingFang SC", "Menlo"))
        self.assertEqual(get_font_names("Linux"), ("Noto Sans CJK SC", "Monospace"))
        self.assertEqual(get_font_names("Windows"), ("Microsoft YaHei UI", "Consolas"))

    def test_get_settings_path_uses_current_working_directory(self):
        cwd = os.path.join("C:\\", "project")

        self.assertEqual(get_settings_path(cwd), os.path.join(cwd, "settings.json"))

    def test_get_icon_path_supports_source_and_frozen_modes(self):
        source_file = os.path.join("C:\\", "project", "src", "linux_do_gui.py")

        self.assertEqual(
            get_icon_path(source_file=source_file, frozen=False),
            os.path.join("C:\\", "project", "assets", "icon.ico"),
        )
        self.assertEqual(
            get_icon_path(frozen=True, meipass=os.path.join("C:\\", "bundle")),
            os.path.join("C:\\", "bundle", "icon.ico"),
        )

    def test_configure_linux_input_method_sets_fcitx_when_available(self):
        env = {}

        configure_linux_input_method(
            system_name="Linux",
            environ=env,
            exists=lambda path: path == "/usr/bin/fcitx5",
        )

        self.assertEqual(env["GTK_IM_MODULE"], "fcitx")
        self.assertEqual(env["QT_IM_MODULE"], "fcitx")
        self.assertEqual(env["XMODIFIERS"], "@im=fcitx")

    def test_configure_linux_input_method_does_not_override_existing_value(self):
        env = {"GTK_IM_MODULE": "custom"}

        configure_linux_input_method(
            system_name="Linux",
            environ=env,
            exists=lambda path: True,
        )

        self.assertEqual(env, {"GTK_IM_MODULE": "custom"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the resource tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_resources -v
```

Expected: `ModuleNotFoundError: No module named 'linux_do.resources'`.

- [ ] **Step 3: Create `src/linux_do/resources.py`**

Create:

```python
import os
import platform
import sys


def configure_linux_input_method(system_name=None, environ=None, exists=None):
    system_name = system_name or platform.system()
    environ = os.environ if environ is None else environ
    exists = os.path.exists if exists is None else exists

    if system_name != "Linux" or "GTK_IM_MODULE" in environ:
        return

    if exists("/usr/bin/fcitx") or exists("/usr/bin/fcitx5"):
        environ["GTK_IM_MODULE"] = "fcitx"
        environ["QT_IM_MODULE"] = "fcitx"
        environ["XMODIFIERS"] = "@im=fcitx"
    elif exists("/usr/bin/ibus"):
        environ["GTK_IM_MODULE"] = "ibus"
        environ["QT_IM_MODULE"] = "ibus"
        environ["XMODIFIERS"] = "@im=ibus"


def get_font_names(system_name=None):
    system_name = system_name or platform.system()
    if system_name == "Darwin":
        return "PingFang SC", "Menlo"
    if system_name == "Linux":
        return "Noto Sans CJK SC", "Monospace"
    return "Microsoft YaHei UI", "Consolas"


def get_icon_path(source_file=None, frozen=None, meipass=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        base_path = meipass if meipass is not None else sys._MEIPASS
        return os.path.join(base_path, "icon.ico")

    source_file = os.path.abspath(source_file or __file__)
    source_dir = os.path.dirname(source_file)
    if os.path.basename(source_dir) == "linux_do":
        project_root = os.path.dirname(os.path.dirname(source_dir))
    else:
        project_root = os.path.dirname(source_dir)
    return os.path.join(project_root, "assets", "icon.ico")


def get_settings_path(cwd=None):
    return os.path.join(cwd or os.getcwd(), "settings.json")


def create_tray_image(color="#0f3460"):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = 4
    draw.ellipse([padding, padding, size - padding, size - padding], fill=color)

    inner_padding = 12
    draw.ellipse(
        [inner_padding, inner_padding, size - inner_padding, size - inner_padding],
        fill="#1a1a2e",
    )

    center = size // 2
    dot_size = 8
    draw.ellipse(
        [center - dot_size, center - dot_size, center + dot_size, center + dot_size],
        fill="#00d9ff",
    )

    return img
```

- [ ] **Step 4: Wire resource helpers into `src/linux_do_gui.py`**

Near the top of `src/linux_do_gui.py`, keep `platform` imported before Tkinter and add:

```python
from linux_do.resources import (
    configure_linux_input_method,
    create_tray_image,
    get_font_names,
    get_icon_path,
    get_settings_path,
)


configure_linux_input_method()
```

Replace the local font selection block with:

```python
FONT_FAMILY, FONT_MONO = get_font_names()
```

Delete the local helper definitions:

```text
def get_icon_path(...)
def get_settings_path(...)
def create_tray_image(...)
```

Keep tray support detection in `src/linux_do_gui.py`, but make it verify both `pystray` and Pillow are importable:

```python
TRAY_SUPPORT = False
if platform.system() != "Darwin":
    try:
        import pystray
        from PIL import Image

        TRAY_SUPPORT = True
    except ImportError:
        TRAY_SUPPORT = False
```

Do not import `ImageDraw` in `src/linux_do_gui.py`; `create_tray_image()` imports it inside `resources.py`.

- [ ] **Step 5: Run resource and full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_resources tests.test_config tests.test_topics tests.test_gui_compatibility tests.test_gui_reply_filter -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit resource extraction**

Run:

```powershell
git add src/linux_do/resources.py src/linux_do_gui.py tests/test_resources.py
git commit -m "refactor: extract resource helpers"
```

## Task 5: Final Verification And Import Smoke Test

**Files:**
- Modify only if verification reveals a concrete import or packaging issue.

- [ ] **Step 1: Run the full unit test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run a compile check**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall src tests
```

Expected: no syntax errors.

- [ ] **Step 3: Run a GUI module import smoke test without opening the GUI**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import sys, types; sys.path.insert(0, 'src'); sys.modules['DrissionPage'] = types.SimpleNamespace(ChromiumPage=object, ChromiumOptions=object); import linux_do_gui; print(linux_do_gui.VERSION); print(len(linux_do_gui.CATS)); print(linux_do_gui.CFG['base'])"
```

Expected output contains:

```text
8.5.0
16
https://linux.do
```

- [ ] **Step 4: Check worktree and recent commits**

Run:

```powershell
git status --short --branch
git log --oneline -5
```

Expected: no unintended unstaged changes. The recent commits should include the design commit, the plan commit, and the three refactor commits.

- [ ] **Step 5: Summarize the result**

Report:

```text
Extracted topic helpers, config defaults, and resource helpers into src/linux_do/.
Kept src/linux_do_gui.py as the launcher and compatibility surface.
Verification passed: unittest discover, compileall, and import smoke test.
```

## Self-Review

- Spec coverage: the plan creates `src/linux_do/`, extracts topic/config/resource helpers, keeps `src/linux_do_gui.py`, preserves old top-level topic helper names, and adds direct tests.
- Placeholder scan: every task has concrete file paths, commands, expected failures, expected passes, and code content.
- Type consistency: function names match the design and existing source names exactly.
- Scope check: `Bot` and `GUI` remain in `src/linux_do_gui.py`; browser automation and UI behavior are not changed.
