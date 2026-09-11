# -*- coding: utf-8 -*-
"""
Linux.do 论坛刷帖助手 v8.4
功能：
1. 自动获取用户等级和升级进度
2. 多板块浏览
3. 随机点赞帖子和回复
4. 随机回帖
5. 统计报告
6. 防风控机制（随机间隔）
7. 升级进度实时追踪
8. 系统托盘支持
9. 快速浏览模式（增加浏览话题数）
10. 真实进度变化统计
"""

import sys, os, random, time, json, threading, subprocess, re
import urllib.request
from copy import deepcopy
from datetime import datetime

import platform

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from linux_do.config import GITHUB_REPO, VERSION, default_categories, default_config
from linux_do.browser_tasks import (
    TaskRegistry, COMPLETED, ERROR, RUNNING, STOPPED, STOPPING,
    STATUS_LABELS, normalize_entries, task_key,
)
from linux_do.resources import (
    configure_linux_input_method,
    create_tray_image,
    get_font_names,
    get_icon_path,
    get_settings_path,
)
from linux_do.session_stats import (
    add_read_progress,
    add_topic_progress,
    new_stats,
    progress_added_for_metric,
)
from linux_do.topics import (
    build_get_topics_js,
    count_topic_candidates,
    filter_topics_by_reply_count,
    merge_topic_payloads,
    parse_reply_count_range,
    select_topic_candidates,
)

# Linux 输入法兼容性修复（必须在导入 tkinter 之前设置）
configure_linux_input_method()

import tkinter as tk
from tkinter import messagebox
from linux_do.browser_table import BrowserTaskTable

FONT_FAMILY, FONT_MONO = get_font_names()

# 托盘支持（macOS 上禁用，因为可能导致 UI 问题）
TRAY_SUPPORT = False
if platform.system() != "Darwin":  # 非 macOS
    try:
        import pystray
        from PIL import Image

        TRAY_SUPPORT = True
    except ImportError:
        TRAY_SUPPORT = False

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except:
    print("pip install DrissionPage")
    sys.exit(1)


CATS = default_categories()
CFG = default_config()


def call_simprint_api(port, api_key, path, payload=None, timeout=60):
    """调用 Simprint 本地 API（POST JSON）。"""
    url = f"http://127.0.0.1:{port}/api/local{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "sp-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def call_bitbrowser_api(port, path, payload=None, timeout=60):
    """调用比特浏览器本地 API（POST JSON）。"""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def normalize_simprint_group_name(name):
    """把 Linux.do / linuxdo / linux.do 等分组名归一成 linuxdo。"""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def is_linuxdo_simprint_group(group_name):
    return normalize_simprint_group_name(group_name) == "linuxdo"


def migrate_simprint_env_label(label):
    """移除旧配置中附加的 ready 状态标记。"""
    return re.sub(r" \[ready\]$", "", str(label or ""))


def extract_linuxdo_simprint_environments(payload):
    """从 Simprint 环境列表响应中筛出 Linux.do 分组下的环境。"""
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    items = data.get("items", []) if isinstance(data, dict) else []
    environments = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        group = item.get("group") or {}
        env = item.get("environment") or {}
        if not isinstance(group, dict) or not isinstance(env, dict):
            continue
        if not is_linuxdo_simprint_group(group.get("name")):
            continue
        env_uuid = env.get("uuid")
        if not env_uuid:
            continue
        environments.append(
            {
                "uuid": str(env_uuid),
                "name": str(env.get("name") or env_uuid),
                "status": str(env.get("status") or ""),
                "group_name": str(group.get("name") or ""),
            }
        )
    return environments


def extract_bitbrowser_windows(payload):
    """从比特浏览器窗口列表响应中提取可选择的窗口信息。"""
    if not isinstance(payload, dict):
        return []

    data = payload.get("data", payload)
    if not isinstance(data, (dict, list)):
        return []

    if isinstance(data, list):
        items = data
    else:
        items = None
        for key in (
            "list",
            "items",
            "browserList",
            "browser_list",
            "windows",
            "data",
        ):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
    if items is None:
        return []

    windows = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        window_id = next(
            (
                item.get(key)
                for key in ("id", "windowId", "window_id", "browserId", "browser_id")
                if item.get(key)
            ),
            None,
        )
        if not window_id:
            continue
        window_id = str(window_id)
        if window_id in seen:
            continue
        seen.add(window_id)
        name = next(
            (
                item.get(key)
                for key in ("name", "title", "browserName", "browser_name", "remark")
                if item.get(key)
            ),
            window_id,
        )
        remark = str(item.get("remark") or "").strip()
        seq = item.get("seq")
        status = next(
            (
                item.get(key)
                for key in ("status", "openStatus", "open_status", "state")
                if item.get(key) not in (None, "")
            ),
            "",
        )
        windows.append(
            {
                "id": window_id,
                "name": str(name),
                "remark": remark,
                "seq": seq,
                "status": str(status),
            }
        )
    return windows


def format_bitbrowser_window_label(window):
    """格式化窗口选择器标签，只显示“序号 - 名字”。"""
    if not isinstance(window, dict):
        return ""
    window_id = str(window.get("id") or "")
    name = str(window.get("name") or window_id).strip()
    seq = window.get("seq")
    seq_text = str(seq).strip() if seq not in (None, "") else "-"
    return f"{seq_text} - {name}"


def migrate_bitbrowser_window_label(label, window_id=""):
    """把旧版“名称... | ID”标签迁移为“序号 - 名称”。"""
    text = str(label or "").strip()
    if re.match(r"^\d+\s+-\s+", text):
        return text

    legacy = text.split(" | ", 1)[0]
    match = re.match(r"^(.*?)\s+#(\d+)(?:\s+\[[^]]*\])?$", legacy)
    if match:
        name = re.sub(r"\s+\([^()]*\)$", "", match.group(1)).strip()
        if name:
            return f"{match.group(2)} - {name}"
    return text


class Bot:
    def __init__(
        s,
        cfg,
        cats,
        lg,
        update_info=None,
        update_progress=None,
        update_countdown=None,
        mode="endless",
        target_value=0,
        enable_like=True,
        enable_reply=True,
        enable_wait=True,
        browse_mode="deep",
        screen_height=None,
    ):
        s.cfg = cfg
        s.cats = cats
        s.lg = lg
        s.update_info = update_info
        s.update_progress = update_progress  # 新增：更新进度回调
        s.update_countdown = update_countdown  # 新增：更新倒计时回调
        s.mode = mode  # 运行模式：endless(无尽), topics(帖子数), time(时间限制)
        s.target_value = target_value  # 目标值：帖子数或分钟数
        s.enable_like = enable_like  # 是否启用自动点赞
        s.enable_reply = enable_reply  # 是否启用自动回复
        s.enable_wait = enable_wait  # 是否启用等待时间
        s.browse_mode = browse_mode  # 浏览模式：deep(深度爬楼), quick(快速浏览3-5层)
        # GUI 由主线程提前读取屏幕高度，避免后台线程重复创建 Tk 根窗口。
        s.screen_height = screen_height
        s.pg = None
        s.run = False
        s._stop_requested = threading.Event()
        s.stats = new_stats()
        s.user_info = None
        s.level_requirements = []  # 保存升级要求
        s.initial_level_info = None  # 保存初始等级信息用于对比
        s.start_time = None  # 记录开始时间

    def _random_delay(s, min_sec=0.5, max_sec=2.0, reason=""):
        """防风控：随机延迟"""
        delay = random.uniform(min_sec, max_sec)
        if reason:
            s.lg(f"[防风控] {reason}，等待 {delay:.1f}s")
        s._stop_requested.wait(delay)

    def _get_screen_height(s):
        """返回用于浏览器窗口布局的屏幕高度。"""
        if s.screen_height:
            return s.screen_height

        # 保留 Bot 独立使用时的兼容路径；GUI 启动时不会走这里。
        try:
            import tkinter as tk

            root = tk.Tk()
            try:
                return root.winfo_screenheight()
            finally:
                root.destroy()
        except Exception:
            return 900

    def _set_connected_window_size(s):
        """连接外部浏览器后设置窗口尺寸，失败时保持原窗口布局。"""
        if not s.pg:
            return
        try:
            s.pg.set.window.size(1200, s._get_screen_height())
        except Exception:
            pass

    def start(s):
        # 确保先关闭旧的浏览器实例
        if s.pg:
            s.lg("关闭旧的浏览器实例...")
            try:
                s.pg.quit()
                time.sleep(1)  # 等待浏览器完全关闭
            except:
                pass
            s.pg = None

        s.lg("启动浏览器...")

        if s.cfg.get("browser_backend") == "bitbrowser":
            return s._start_bitbrowser()
        if s.cfg.get("browser_backend") == "simprint":
            return s._start_simprint()

        return s._start_builtin()

    def _start_builtin(s):
        """启动内置 Chromium，保留原有 404 重试策略。"""
        # 重试机制（处理 404 错误）
        max_retries = 3
        for attempt in range(max_retries):
            if s._stop_requested.is_set():
                return False
            try:
                co = ChromiumOptions()

                # 设置用户数据目录
                user_data_dir = os.path.join(os.getcwd(), "browser_data")
                co.set_user_data_path(user_data_dir)

                if s.cfg["proxy"]:
                    co.set_proxy(s.cfg["proxy"])
                co.set_argument("--disable-blink-features=AutomationControlled")

                # 设置窗口大小：宽度1200，高度为屏幕高度
                screen_height = s._get_screen_height()
                co.set_argument(f"--window-size=1200,{screen_height}")
                s.lg(f"设置浏览器窗口大小: 1200x{screen_height}")

                s.pg = ChromiumPage(co)
                s.lg("浏览器就绪")
                return True

            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg and attempt < max_retries - 1:
                    s.lg(f"启动失败（尝试 {attempt + 1}/{max_retries}），重试中...")
                    time.sleep(2)
                    continue
                else:
                    s.lg(f"启动失败: {error_msg}")
                    return False

        return False

    def _bit_api(s, path, payload, timeout=60, port=None):
        """调用比特浏览器本地 API（POST JSON）"""
        port = port or s.cfg.get("bit_api_port", 54345)
        return call_bitbrowser_api(port, path, payload, timeout=timeout)

    def _simprint_api(s, path, payload, timeout=60):
        """调用 Simprint 本地 API（POST JSON）。"""
        port = s.cfg.get("simprint_api_port", 8080)
        api_key = (s.cfg.get("simprint_api_key") or "").strip()
        return call_simprint_api(port, api_key, path, payload, timeout=timeout)

    def _extract_debug_address(s, data):
        """从 API 返回中提取可能存在的 CDP 调试地址。"""
        if not isinstance(data, dict):
            return ""
        for key in (
            "http",
            "ws",
            "debuggingAddress",
            "debugging_address",
            "remoteDebuggingAddress",
            "remote_debugging_address",
            "debuggerAddress",
            "debugger_address",
        ):
            value = data.get(key)
            if value:
                return str(value).replace("ws://", "").replace("http://", "").split("/")[0]
        for key in ("debuggingPort", "debugging_port", "remoteDebuggingPort"):
            value = data.get(key)
            if value:
                return f"127.0.0.1:{value}"
        for value in data.values():
            nested = s._extract_debug_address(value)
            if nested:
                return nested
        return ""

    def _simprint_command_lines(s, env_uuid):
        """读取当前进程命令行，用于找到 Simprint 暴露的 remote debugging 端口。"""
        if platform.system() == "Windows":
            ps_script = (
                "$envUuid = '" + env_uuid.replace("'", "''") + "'; "
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -and $_.CommandLine.Contains('--simprint-env-id=' + $envUuid) } | "
                "ForEach-Object { $_.CommandLine }"
            )
            for shell_name in ("powershell", "pwsh"):
                try:
                    result = subprocess.run(
                        [shell_name, "-NoProfile", "-Command", ps_script],
                        capture_output=True,
                        text=True,
                        timeout=8,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.splitlines()
                except Exception:
                    continue
            return []

        try:
            result = subprocess.run(
                ["ps", "-eo", "command"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode != 0:
                return []
            return [
                line
                for line in result.stdout.splitlines()
                if f"--simprint-env-id={env_uuid}" in line
            ]
        except Exception:
            return []

    def _find_simprint_debug_address(s, env_uuid, timeout=20):
        """等待 Simprint 浏览器进程出现，并提取 remote debugging 端口。"""
        deadline = time.time() + timeout
        pattern = re.compile(r"--remote-debugging-port=(\d+)")
        while time.time() < deadline and not s._stop_requested.is_set():
            for command_line in s._simprint_command_lines(env_uuid):
                match = pattern.search(command_line)
                if match:
                    return f"127.0.0.1:{match.group(1)}"
            s._stop_requested.wait(0.5)
        return ""

    def _start_bitbrowser(s):
        """通过比特浏览器 API 打开窗口并接管其 CDP 调试端口"""
        win_id = (s.cfg.get("bit_window_id") or "").strip()
        if not win_id:
            s.lg("未填写比特浏览器窗口ID")
            return False
        try:
            s.lg(f"通过比特浏览器打开窗口 {win_id} ...")
            resp = s._bit_api("/browser/open", {"id": win_id})
            if not resp or not resp.get("success"):
                msg = resp.get("msg") if resp else "无响应"
                s.lg(f"比特浏览器打开失败: {msg}")
                return False

            data = resp.get("data", {}) or {}
            # http 字段即 CDP 调试地址（形如 127.0.0.1:54388）
            addr = data.get("http") or data.get("ws") or ""
            addr = addr.replace("ws://", "").replace("http://", "").split("/")[0]
            if not addr:
                s.lg("比特浏览器未返回调试地址")
                return False

            s.lg(f"连接调试地址: {addr}")
            co = ChromiumOptions().set_address(addr)
            s.pg = ChromiumPage(co)

            # 连接后再设置窗口尺寸（比特浏览器模式无法用启动参数）
            s._set_connected_window_size()

            s.lg("比特浏览器就绪")
            return True
        except Exception as e:
            s.lg(f"比特浏览器启动失败: {e}")
            s.lg("请确认：比特浏览器客户端已打开、本地API已开启、端口与窗口ID正确")
            return False

    def _start_simprint(s):
        """通过 Simprint API 打开环境并接管其 CDP 调试端口。"""
        env_uuid = (s.cfg.get("simprint_env_uuid") or "").strip()
        api_key = (s.cfg.get("simprint_api_key") or "").strip()
        if not env_uuid:
            s.lg("未选择 Simprint 环境")
            return False
        if not api_key:
            s.lg("未填写 Simprint API Key")
            return False
        try:
            s.lg(f"通过 Simprint 打开环境 {env_uuid} ...")
            resp = s._simprint_api("/environments/start", {"envUuid": env_uuid})
            if not resp or resp.get("code") != 1:
                msg = resp.get("message") or resp.get("msg") if resp else "无响应"
                s.lg(f"Simprint 打开失败: {msg}")
                return False

            data = resp.get("data", {}) or {}
            if isinstance(data, dict) and data.get("success") is False:
                s.lg("Simprint 打开失败: success=false")
                return False

            addr = s._extract_debug_address(data)
            if not addr:
                s.lg("Simprint 未在 API 返回调试地址，尝试从进程中查找端口...")
                addr = s._find_simprint_debug_address(env_uuid)
            if not addr:
                s.lg("Simprint 未找到 remote debugging 端口")
                return False

            s.lg(f"连接 Simprint 调试地址: {addr}")
            co = ChromiumOptions().set_address(addr)
            s.pg = ChromiumPage(co)

            s._set_connected_window_size()

            s.lg("Simprint 就绪")
            return True
        except Exception as e:
            s.lg(f"Simprint 启动失败: {e}")
            s.lg("请确认：Simprint 客户端已打开、本地API已开启、端口/API Key正确且已选择环境")
            return False

    def stop(s):
        s._stop_requested.set()
        s.run = False

    def close(s):
        if s.cfg.get("browser_backend") == "bitbrowser":
            win_id = (s.cfg.get("bit_window_id") or "").strip()
            if win_id:
                try:
                    s.lg("通过比特浏览器关闭窗口...")
                    s._bit_api("/browser/close", {"id": win_id}, timeout=30)
                except Exception as e:
                    s.lg(f"关闭比特浏览器窗口出错: {e}")
            s.pg = None
            return
        if s.cfg.get("browser_backend") == "simprint":
            env_uuid = (s.cfg.get("simprint_env_uuid") or "").strip()
            if env_uuid:
                try:
                    s.lg("通过 Simprint 关闭环境...")
                    s._simprint_api("/environments/stop", {"envUuid": env_uuid}, timeout=30)
                except Exception as e:
                    s.lg(f"关闭 Simprint 环境出错: {e}")
            s.pg = None
            return
        if s.pg:
            try:
                s.pg.quit()
                time.sleep(0.5)  # 等待浏览器关闭
            except Exception as e:
                s.lg(f"关闭浏览器时出错: {e}")
            s.pg = None  # 清空引用

    def check_login(s, wait_for_login=True, max_wait=600, check_interval=15):
        """
        检查登录状态
        wait_for_login: 是否等待用户登录
        max_wait: 最大等待时间（秒）
        check_interval: 检查间隔（秒）
        """
        s.lg("检查登录...")
        s.pg.get(s.cfg["base"])
        if s._stop_requested.wait(3):
            return False

        start_time = time.time()
        check_count = 0
        first_check = True

        while s.run:
            check_count += 1
            try:
                # 不刷新页面，直接检查当前页面的登录状态
                user_ele = s.pg.ele("#current-user", timeout=3)
                if user_ele:
                    try:
                        img = s.pg.ele("#current-user img", timeout=2)
                        s.user_info = {"username": img.attr("title") if img else "用户"}
                    except:
                        s.user_info = {"username": "用户"}
                    s.lg("已登录: " + s.user_info["username"])
                    return True
            except Exception as e:
                pass  # 未找到登录元素，继续等待

            # 未登录
            if not wait_for_login:
                s.lg("未登录，请先登录")
                return False

            # 检查是否超时
            elapsed = time.time() - start_time
            remaining = max_wait - elapsed

            if remaining <= 0:
                s.lg("等待登录超时，请重新启动")
                return False

            if first_check:
                s.lg("未检测到登录，请在浏览器中完成登录")
                s.lg("提示：登录成功后会自动检测，无需其他操作")
                s.lg(f"检查间隔：{check_interval}秒，最长等待：{int(remaining)}秒")
                first_check = False
            else:
                s.lg(f"第{check_count}次检查，未检测到登录，剩余等待{int(remaining)}秒")

            # 等待一段时间后重新检查（不刷新页面，避免打断用户输入）
            s._stop_requested.wait(check_interval)

        return False

    def get_level_info(s, is_final=False):
        """获取等级信息"""
        s.lg("获取等级信息...")
        try:
            # 如果是最终获取，先强制刷新页面确保数据最新
            if is_final:
                s.lg("强制刷新页面获取最新数据...")
                s.pg.get(s.cfg["connect"])
                time.sleep(2)
                # 刷新页面
                s.pg.run_js("location.reload(true)")
                time.sleep(4)
            else:
                s.pg.get(s.cfg["connect"])
                time.sleep(4)

            info = s.pg.run_js("""
            function getLevelInfo() {
                const result = {
                    username: '',
                    level: '',
                    nextLevel: '',
                    requirements: []
                };

                // 获取用户名（从 card-subtitle 中提取）
                const subtitle = document.querySelector('.card-subtitle');
                if (subtitle) {
                    const text = subtitle.textContent;
                    const match = text.match(/@([^\\s·]+)/);
                    if (match) {
                        result.username = match[1];
                    }
                }

                // 获取下一级要求（从 card-title 中提取）
                const cardTitle = document.querySelector('.card-title');
                if (cardTitle) {
                    const text = cardTitle.textContent;
                    const match = text.match(/信任级别\\s*(\\d+)/);
                    if (match) {
                        result.nextLevel = match[1];
                        // 当前等级 = 目标等级 - 1
                        result.level = String(parseInt(match[1]) - 1);
                    }
                }

                // 获取活跃程度数据（tl3-ring 结构）
                const rings = document.querySelectorAll('.tl3-ring');
                rings.forEach(ring => {
                    const label = ring.querySelector('.tl3-ring-label');
                    const current = ring.querySelector('.tl3-ring-current');
                    const target = ring.querySelector('.tl3-ring-target');

                    if (label && current && target) {
                        const name = label.textContent.trim();
                        const currentVal = current.textContent.trim();
                        const targetVal = target.textContent.replace('/', '').trim();

                        result.requirements.push({
                            name: name,
                            current: currentVal,
                            required: targetVal
                        });
                    }
                });

                // 获取互动参与数据（tl3-bar 结构）
                const bars = document.querySelectorAll('.tl3-bar-item');
                bars.forEach(bar => {
                    const label = bar.querySelector('.tl3-bar-label');
                    const nums = bar.querySelector('.tl3-bar-nums');

                    if (label && nums) {
                        const name = label.textContent.trim();
                        const numsText = nums.textContent.trim();
                        const match = numsText.match(/(\\d+)\\/(\\d+)/);

                        if (match) {
                            result.requirements.push({
                                name: name,
                                current: match[1],
                                required: match[2]
                            });
                        }
                    }
                });

                // 获取合规记录数据（tl3-quota 结构）
                const quotas = document.querySelectorAll('.tl3-quota-card');
                quotas.forEach(quota => {
                    const label = quota.querySelector('.tl3-quota-label');
                    const nums = quota.querySelector('.tl3-quota-nums');

                    if (label && nums) {
                        const name = label.textContent.trim();
                        const numsText = nums.textContent.trim();
                        const match = numsText.match(/(\\d+)\\s*\\/\\s*(\\d+)/);

                        if (match) {
                            result.requirements.push({
                                name: name,
                                current: match[1],
                                required: match[2]
                            });
                        }
                    }
                });

                // 获取禁言/封禁数据（tl3-veto 结构）
                const vetos = document.querySelectorAll('.tl3-veto-item');
                vetos.forEach(veto => {
                    const label = veto.querySelector('.tl3-veto-label');
                    const value = veto.querySelector('.tl3-veto-value');

                    if (label && value) {
                        const name = label.textContent.trim();
                        const currentVal = value.textContent.trim();

                        result.requirements.push({
                            name: name,
                            current: currentVal,
                            required: '0'
                        });
                    }
                });

                return result;
            }
            return getLevelInfo();
            """)

            if info:
                s.user_info = info
                s.lg("用户: " + info.get("username", "未知"))
                s.lg("当前等级: " + info.get("level", "未知") + "级")
                if info.get("nextLevel"):
                    s.lg("下一级: " + info.get("nextLevel") + "级")
                if info.get("requirements"):
                    s.lg("升级要求:")
                    for req in info["requirements"][:8]:
                        s.lg(
                            "  "
                            + req["name"]
                            + ": "
                            + req["current"]
                            + "/"
                            + req["required"]
                        )

                # 更新GUI显示
                if s.update_info:
                    s.update_info(info, is_final)

                # 保存升级要求用于进度追踪
                s.level_requirements = info.get("requirements", [])

                # 首次获取时保存初始等级信息
                if not is_final and s.initial_level_info is None:
                    s.initial_level_info = info.copy()

                return info
        except Exception as e:
            s.lg("获取等级失败: " + str(e))
        return None

    def get_topics(s, cat):
        """获取帖子列表，必要时下滑加载更多，再按回复数范围筛选。"""
        url = s.cfg["base"] + cat["u"]
        s.lg("进入板块: " + cat["n"])
        s.pg.get(url)
        s._random_delay(2, 4, "页面加载")

        reply_min = s.cfg.get("reply_count_min", 0)
        reply_max = s.cfg.get("reply_count_max", 120)
        unread_only = s.cfg.get("unread_only", True)
        list_scroll_times = max(0, int(s.cfg.get("list_scroll_times", 3)))
        target_candidates = max(1, int(s.cfg.get("topic_candidate_target", 8)))

        topics = {"unread": [], "read": [], "all": []}
        previous_total = 0

        for scan_index in range(list_scroll_times + 1):
            current_topics = s.pg.run_js(build_get_topics_js()) or {}
            topics = merge_topic_payloads(topics, current_topics)
            total_loaded = len(topics.get("all", []))
            candidate_count = count_topic_candidates(
                topics, reply_min, reply_max, unread_only=unread_only
            )

            s.lg(
                f"列表扫描 {scan_index + 1}/{list_scroll_times + 1}: "
                f"已加载 {total_loaded} 个话题，符合条件 {candidate_count} 个"
            )

            if candidate_count >= target_candidates:
                break
            if scan_index >= list_scroll_times or not s.run:
                break
            if scan_index > 0 and total_loaded == previous_total:
                s.lg("下滑后没有加载到更多话题，停止加载")
                break

            previous_total = total_loaded
            s.lg("符合条件的话题不足，向下滑动列表加载更多...")
            s.pg.run_js("window.scrollTo(0, document.body.scrollHeight)")
            s._random_delay(1.5, 2.5, "等待列表加载更多")

        if topics:
            unread_count = len(topics.get("unread", []))
            read_count = len(topics.get("read", []))
            s.lg(f"找到 {unread_count} 个未读话题，{read_count} 个已读话题")

            max_label = "不限" if reply_max is None else str(reply_max)
            filtered_unread = filter_topics_by_reply_count(
                topics.get("unread", []), reply_min, reply_max
            )
            filtered_read = filter_topics_by_reply_count(
                topics.get("read", []), reply_min, reply_max
            )
            s.lg(
                f"回复数范围 {reply_min}-{max_label}，筛选后 "
                f"{len(filtered_unread)} 个未读话题，{len(filtered_read)} 个已读话题"
            )

            candidates = select_topic_candidates(
                topics, reply_min, reply_max, unread_only=unread_only
            )
            if not candidates:
                if unread_only:
                    s.lg("只浏览未读已开启，没有符合回复数范围的未读话题，跳过该板块")
                else:
                    s.lg("没有符合回复数范围的帖子，跳过该板块")
                return []

            # 优先返回未读话题，如果未读话题少于3个，补充一些已读话题
            if filtered_unread:
                if unread_only:
                    s.lg(f"只浏览未读，候选 {len(filtered_unread)} 个未读话题")
                    return candidates
                s.lg(f"优先浏览 {len(filtered_unread)} 个未读话题")
                # 如果未读话题较少，可以补充一些已读话题
                if len(filtered_unread) < 3 and filtered_read:
                    s.lg(
                        f"未读话题较少，补充 {min(3, len(filtered_read))} 个已读话题"
                    )
                return candidates
            else:
                s.lg("没有未读话题，浏览已读话题")
                return candidates

        return []

    def get_floor_info(s):
        """获取楼层信息（当前楼层/总楼层）

        支持两种显示格式：
        1. 宽窗口：.timeline-replies 显示 "1/169"
        2. 窄窗口：#topic-progress .nums 显示 <span>69</span><span>/</span><span>74</span>
        """
        floor_info = s.pg.run_js("""
        function getFloorInfo() {
            // 方法1：尝试从 .timeline-replies 获取（宽窗口）
            const timelineElement = document.querySelector('.timeline-replies');
            if (timelineElement) {
                const text = timelineElement.textContent.trim();
                const match = text.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
                if (match) {
                    return {
                        current: parseInt(match[1]),
                        total: parseInt(match[2]),
                        source: 'timeline-replies'
                    };
                }
            }
            
            // 方法2：尝试从 #topic-progress .nums 获取（窄窗口）
            const progressElement = document.querySelector('#topic-progress .nums');
            if (progressElement) {
                const spans = progressElement.querySelectorAll('span');
                if (spans.length >= 3) {
                    const current = parseInt(spans[0].textContent);
                    const total = parseInt(spans[2].textContent);
                    if (!isNaN(current) && !isNaN(total)) {
                        return {
                            current: current,
                            total: total,
                            source: 'topic-progress'
                        };
                    }
                }
            }
            
            return null;
        }
        return getFloorInfo();
        """)

        return floor_info

    def scroll_page(s, duration=None, quick_mode=False):
        """爬楼模式 - 使用楼层计数器跟踪进度

        quick_mode: 快速浏览模式，只爬3-5层就返回
        返回值: 实际爬过的楼层数（结束楼层 - 开始楼层）
        """
        # 如果是快速浏览模式或者Bot设置为quick模式
        if quick_mode or s.browse_mode == "quick":
            return s._scroll_page_quick()

        # 获取初始楼层信息
        floor_info = s.get_floor_info()
        if not floor_info:
            s.lg("⚠ 无法获取楼层信息，使用传统滚动模式")
            # 降级到传统滚动模式
            s._scroll_page_legacy(duration)
            return 0

        total_floors = floor_info["total"]
        start_floor = floor_info["current"]  # 记录开始楼层
        s.lg(
            f"帖子总楼层数: {total_floors}，开始楼层: {start_floor} (来源: {floor_info.get('source', 'unknown')})"
        )

        if total_floors < 10:
            s.lg(f"楼层数太少（{total_floors}），使用快速浏览")
            s._scroll_page_legacy(duration)
            floors_climbed = max(0, total_floors - start_floor)
            add_read_progress(s.stats, floors_climbed)
            if floors_climbed and s.update_progress:
                s.update_progress(s.stats)
            if floors_climbed:
                s._update_countdown_display()
            return floors_climbed

        scroll_count = 0
        current_floor = start_floor
        last_floor = start_floor
        stuck_count = 0  # 楼层卡住计数

        # 开始爬楼
        while current_floor < total_floors and s.run:
            # 检查是否达到目标（深度爬楼模式下实时检查）
            if s._check_target_reached():
                s.lg(f"已达到目标，停止爬楼")
                s.run = False
                break

            # 等待阅读（2-4秒）
            wait_time = random.uniform(2, 4)
            time.sleep(wait_time)

            # 滚动页面（600-1200px）
            scroll_distance = random.randint(600, 1200)
            s.pg.run_js(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1

            # 等待页面更新
            time.sleep(0.5)

            # 获取当前楼层
            floor_info = s.get_floor_info()
            if floor_info:
                current_floor = floor_info["current"]

                if current_floor > last_floor:
                    # 计算本次爬过的楼层数并累加到统计
                    floors_climbed = current_floor - last_floor
                    add_read_progress(s.stats, floors_climbed)

                    s.lg(
                        f"爬楼 #{scroll_count} → 当前: {current_floor}/{total_floors} 楼 (本帖已爬 {current_floor - start_floor} 层)"
                    )
                    last_floor = current_floor
                    stuck_count = 0

                    # 实时更新进度和倒计时
                    if s.update_progress:
                        s.update_progress(s.stats)
                    s._update_countdown_display()
                else:
                    stuck_count += 1

                    # 如果楼层长时间不变，尝试更大的滚动
                    if stuck_count >= 3:
                        s.lg("楼层卡住，加大滚动距离")
                        s.pg.run_js(f"window.scrollBy(0, 1500)")
                        time.sleep(1)
                        stuck_count = 0

            # 安全检查：避免无限循环
            if scroll_count >= 200:
                s.lg("达到最大滚动次数，停止爬楼")
                break

        # 计算实际爬过的楼层数
        floors_climbed_total = current_floor - start_floor
        s.lg(
            f"爬楼完成: 滚动 {scroll_count} 次，从 {start_floor} 爬到 {current_floor}，共爬 {floors_climbed_total} 层"
        )
        return floors_climbed_total

    def _scroll_page_quick(s):
        """快速浏览模式 - 只爬3-5层就返回，用于增加浏览话题数量
        返回值: 实际爬过的楼层数（结束楼层 - 开始楼层）
        """
        floor_info = s.get_floor_info()
        if not floor_info:
            s.lg("⚠ 无法获取楼层信息，快速滚动3次（不计入可确认阅读数）")
            for i in range(3):
                if not s.run:
                    break
                time.sleep(random.uniform(1, 2))
                s.pg.run_js(f"window.scrollBy(0, {random.randint(400, 800)})")
            return 0

        total_floors = floor_info["total"]
        start_floor = floor_info["current"]  # 记录开始楼层
        target_climb = random.randint(3, 5)  # 目标爬3-5层

        s.lg(
            f"[快速浏览] 开始楼层: {start_floor}，目标爬: {target_climb} 层 (总楼层: {total_floors})"
        )

        scroll_count = 0
        current_floor = start_floor
        last_floor = start_floor

        while (
            (current_floor - start_floor) < target_climb
            and current_floor < total_floors
            and s.run
        ):
            # 快速等待（1-2秒）
            time.sleep(random.uniform(1, 2))

            # 滚动页面
            scroll_distance = random.randint(400, 800)
            s.pg.run_js(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1

            time.sleep(0.3)

            # 获取当前楼层
            floor_info = s.get_floor_info()
            if floor_info:
                current_floor = floor_info["current"]
                if current_floor > last_floor:
                    # 计算本次爬过的楼层数并累加
                    floors_climbed = current_floor - last_floor
                    add_read_progress(s.stats, floors_climbed)
                    last_floor = current_floor

                    # 实时更新进度和倒计时
                    if s.update_progress:
                        s.update_progress(s.stats)
                    s._update_countdown_display()

            # 安全检查
            if scroll_count >= 10:
                break

        floors_climbed_total = current_floor - start_floor
        s.lg(
            f"[快速浏览] 完成: 从 {start_floor} 爬到 {current_floor}，共爬 {floors_climbed_total} 层"
        )
        return floors_climbed_total

    def _scroll_page_legacy(s, duration=None):
        """传统滚动模式 - 用于无法获取楼层信息的情况"""
        if duration is None:
            duration = random.uniform(8, 15)

        s.lg(f"传统滚动模式 {duration:.1f}s...")
        start = time.time()
        while time.time() - start < duration and s.run:
            dist = random.randint(150, 400)
            s.pg.run_js(f"window.scrollBy(0, {dist})")
            time.sleep(random.uniform(1.0, 3.0))

            at_bottom = s.pg.run_js("""
            return (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 100;
            """)
            if at_bottom:
                s._random_delay(1, 3, "阅读完毕")
                break
        return 0

    def do_like(s, index=0):
        """点赞"""
        if s._stop_requested.is_set():
            return False
        try:
            result = s.pg.run_js(f"""
            function clickLike(idx) {{
                const buttons = document.querySelectorAll('button.btn-toggle-reaction-like');
                if (buttons.length > idx) {{
                    const btn = buttons[idx];
                    if (!btn.classList.contains('has-like') && !btn.classList.contains('my-likes')) {{
                        btn.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                        setTimeout(() => btn.click(), 300);
                        return true;
                    }}
                }}
                return false;
            }}
            return clickLike({index});
            """)

            if result:
                s._random_delay(0.8, 1.5, "点赞后")
                if index == 0:
                    s.stats["like"] += 1
                    s.lg("点赞主帖成功")
                else:
                    s.stats["like_reply"] += 1
                    s.lg(f"点赞回复 #{index} 成功")
                # 更新进度
                if s.update_progress:
                    s.update_progress(s.stats)
                return True
        except Exception as e:
            s.lg("点赞失败: " + str(e))
        return False

    def do_reply(s, content=None):
        """回帖"""
        if s._stop_requested.is_set():
            return False
        try:
            if content is None:
                content = random.choice(s.cfg["tpl"])

            s.lg("准备回复: " + content)

            # 点击回复按钮
            clicked = s.pg.run_js("""
            function clickReply() {
                const btn = document.querySelector('.topic-footer-main-buttons button.create');
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            }
            return clickReply();
            """)

            if not clicked:
                s.lg("未找到回复按钮")
                return False

            s._random_delay(1.5, 3, "等待编辑器")

            # 输入内容 - 使用安全的方式传递内容
            s.pg.run_js(f"""
            (function() {{
                const textarea = document.querySelector('#reply-control textarea, .d-editor-input');
                if (textarea) {{
                    textarea.focus();
                    textarea.value = '{content}';
                    textarea.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}
            }})();
            """)

            s._random_delay(0.8, 1.5, "输入内容后")

            # 提交
            submitted = s.pg.run_js("""
            function submit() {
                const btn = document.querySelector('#reply-control button.create');
                if (btn && !btn.disabled) {
                    btn.click();
                    return true;
                }
                return false;
            }
            return submit();
            """)

            if submitted:
                s._random_delay(2, 4, "回复提交后")
                s.stats["reply"] += 1
                s.lg("回复成功")
                # 更新进度
                if s.update_progress:
                    s.update_progress(s.stats)
                return True
            else:
                s.lg("提交失败")

        except Exception as e:
            s.lg("回复失败: " + str(e))
        return False

    def browse_topic(s, topic):
        """浏览帖子 - 通过点击链接而不是直接访问URL"""
        title = topic["title"]
        topic_id = topic.get("id", "")
        is_unread = topic.get("isUnread", False)

        if is_unread:
            s.lg("浏览未读话题: " + title)
        else:
            s.lg("浏览已读话题: " + title)

        try:
            # 关键修改：通过点击链接进入话题，而不是直接 get URL
            # 这样才能让"浏览话题"计数增加
            clicked = s.pg.run_js(f"""
            function clickTopic() {{
                // 查找对应的话题链接
                const topicRow = document.querySelector('tr.topic-list-item[data-topic-id="{topic_id}"]');
                if (!topicRow) {{
                    console.log('未找到话题行');
                    return false;
                }}

                const link = topicRow.querySelector('a.title.raw-link.raw-topic-link');
                if (!link) {{
                    console.log('未找到话题链接');
                    return false;
                }}

                // 点击链接（不是新标签）
                link.click();
                return true;
            }}
            return clickTopic();
            """)

            if not clicked:
                s.lg("点击话题失败，跳过")
                return False

            # 等待页面加载
            s._random_delay(3, 5, "话题页面加载")

            # 注意：小蓝点在板块列表页面，不在话题详情页面
            # 所以我们在这里只需要确保页面加载完成即可
            s.lg("话题页面已加载")

            add_topic_progress(s.stats)

            # 更新进度
            if s.update_progress:
                s.update_progress(s.stats)

            # 更新倒计时
            s._update_countdown_display()

            # 爬楼阅读（scroll_page内部会实时更新stats["floors"]和进度）
            s.scroll_page()
            if not s.run:
                return True

            s._random_delay(1, 2, "阅读后")

            # 获取点赞按钮数量
            btn_count = (
                s.pg.run_js("""
            return document.querySelectorAll('button.btn-toggle-reaction-like').length;
            """)
                or 0
            )

            s.lg(f"找到 {btn_count} 个点赞按钮")

            # 随机点赞主帖（检查开关）
            if s.enable_like and btn_count > 0 and random.random() < s.cfg["like_rate"]:
                s.do_like(0)
                if s.enable_wait:
                    s._random_delay(s.cfg["wait_min"], s.cfg["wait_max"], "点赞后休息")

            # 随机点赞回复（检查开关）
            if s.enable_like and btn_count > 1:
                for i in range(1, min(btn_count, 5)):
                    if random.random() < s.cfg["like_reply_rate"]:
                        s.do_like(i)
                        if s.enable_wait:
                            s._random_delay(
                                s.cfg["wait_min"], s.cfg["wait_max"], "点赞回复后"
                            )

            # 随机回帖（检查开关）
            if s.enable_reply and random.random() < s.cfg["reply_rate"]:
                if s.enable_wait:
                    s._random_delay(s.cfg["wait_min"], s.cfg["wait_max"], "准备回帖")
                s.do_reply()

            # 关键修改：返回板块列表
            s.lg("返回板块列表...")
            s.pg.back()
            s._random_delay(2, 3, "返回后等待")

            # 如果是未读话题，检查小蓝点是否消失（确认已被标记为已读）
            if is_unread:
                badge_gone = s.pg.run_js(f"""
                function checkBadgeGone() {{
                    const topicRow = document.querySelector('tr.topic-list-item[data-topic-id="{topic_id}"]');
                    if (!topicRow) {{
                        return true;  // 找不到行，可能已刷新
                    }}
                    // 检查小蓝点是否还存在
                    const badge = topicRow.querySelector('.badge.badge-notification.new-topic');
                    return !badge;  // 返回 true 表示小蓝点已消失
                }}
                return checkBadgeGone();
                """)

                if badge_gone:
                    s.lg("✓ 小蓝点已消失，话题已标记为已读")
                else:
                    s.lg("⚠ 小蓝点仍存在，可能需要更长浏览时间")

            return True
        except Exception as e:
            s.lg("浏览失败: " + str(e))
            # 失败时也尝试返回
            try:
                s.pg.back()
                time.sleep(1)
            except:
                pass
            return False

    def _update_countdown_display(s):
        """更新倒计时显示"""
        if not s.update_countdown or not s.start_time:
            return

        elapsed_time = time.time() - s.start_time
        elapsed_minutes = int(elapsed_time / 60)
        elapsed_seconds = int(elapsed_time % 60)

        topics = s.stats.get("topic", 0)
        floors = s.stats.get("floors", 0)
        total_read = s.stats.get("posts_read", topics + floors)
        read_desc = f"话题{topics}+楼{floors}"
        progress_value = topics if s.browse_mode == "quick" else total_read

        if s.mode == "topics":
            remaining = s.target_value - progress_value
            text = f"剩余: {remaining} | 已读: {total_read} ({read_desc}) | 用时: {elapsed_minutes}:{elapsed_seconds:02d}"
        elif s.mode == "time":
            elapsed_secs = elapsed_time
            remaining_secs = s.target_value * 60 - elapsed_secs
            if remaining_secs > 0:
                remaining_mins = int(remaining_secs / 60)
                remaining_s = int(remaining_secs % 60)
                text = f"剩余: {remaining_mins}:{remaining_s:02d} | 已读: {total_read} ({read_desc})"
            else:
                text = f"已超时 | 已读: {total_read} ({read_desc})"
        else:  # endless
            text = f"用时: {elapsed_minutes}:{elapsed_seconds:02d} | 已读: {total_read} ({read_desc})"

        s.update_countdown(text)

    def _check_target_reached(s):
        """检查是否达到目标，返回True表示应该停止"""
        if s.mode == "topics":
            if s.browse_mode == "quick":
                # 快速浏览模式：只计算主题数
                return s.stats.get("topic", 0) >= s.target_value
            else:
                # 深度爬楼模式：计算主题+楼层
                total_read = s.stats.get(
                    "posts_read", s.stats.get("topic", 0) + s.stats.get("floors", 0)
                )
                return total_read >= s.target_value
        elif s.mode == "time":
            if s.start_time:
                elapsed_minutes = (time.time() - s.start_time) / 60
                return elapsed_minutes >= s.target_value
        return False

    def browse_cat(s, cat):
        """浏览板块"""
        # 先检查是否已达到目标
        if s._check_target_reached():
            return 0

        topics = s.get_topics(cat)
        s.lg(f"找到 {len(topics)} 个帖子")

        if not topics:
            return 0

        # 随机选择几个帖子
        count = min(random.randint(3, 8), len(topics))
        selected = random.sample(topics, count)

        browsed = 0
        for topic in selected:
            if not s.run:
                break

            # 检查是否已达到目标
            if s._check_target_reached():
                s.run = False
                break

            # 浏览话题（内部会自动返回板块列表）
            success = s.browse_topic(topic)
            if success:
                browsed += 1

            # 再次检查是否已达到目标
            if s._check_target_reached():
                s.run = False
                break

            # 防风控：帖子之间随机等待（检查开关）
            # 注意：browse_topic 返回时已经有等待，这里可以减少等待时间
            if s.run and s.enable_wait:
                s._random_delay(0.5, 1.5, "准备下一个话题")

        return browsed

    def run_session(s):
        if s._stop_requested.is_set():
            return STOPPED
        s.run = True
        s.stats = new_stats()
        s.start_time = time.time()  # 记录开始时间

        browser_started = False
        try:
            browser_started = s.start()
            if not browser_started:
                return STOPPED if s._stop_requested.is_set() else ERROR
            if s._stop_requested.is_set():
                return STOPPED
            if not s.check_login(wait_for_login=True, max_wait=300, check_interval=5):
                s.lg("登录检查失败或超时，任务终止")
                return STOPPED if s._stop_requested.is_set() else ERROR

            # 获取等级信息
            s.get_level_info()

            # 获取启用的板块
            enabled = [c for c in s.cats if c.get("e", True)]
            if not enabled:
                s.lg("未选择板块，任务终止")
                return ERROR
            random.shuffle(enabled)

            # 显示运行模式
            if s.mode == "topics":
                s.lg("=" * 30)
                s.lg(f"运行模式: 帖子数量限制 (目标: {s.target_value} 个帖子)")
                s.lg("=" * 30)
            elif s.mode == "time":
                s.lg("=" * 30)
                s.lg(f"运行模式: 时间限制 (目标: {s.target_value} 分钟)")
                s.lg("=" * 30)
            else:
                s.lg("=" * 30)
                s.lg("运行模式: 无尽模式 (手动停止)")
                s.lg("=" * 30)

            # 显示功能开关状态
            features = []
            if s.enable_like:
                features.append("自动点赞")
            if s.enable_reply:
                features.append("自动回复")
            if s.enable_wait:
                features.append("等待延迟")
            s.lg(f"启用功能: {', '.join(features) if features else '仅浏览'}")

            s.lg(f"开始浏览 {len(enabled)} 个板块")
            s.lg("=" * 30)

            # 无尽循环板块
            while s.run:
                for cat in enabled:
                    if not s.run:
                        break

                    # 检查是否达到目标
                    if s._check_target_reached():
                        if s.browse_mode == "quick":
                            s.lg(
                                f"已达到目标主题数: {s.stats.get('topic', 0)}/{s.target_value}"
                            )
                        else:
                            total_read = s.stats.get(
                                "posts_read",
                                s.stats.get("topic", 0) + s.stats.get("floors", 0),
                            )
                            s.lg(
                                f"已达到目标已读数: {total_read}/{s.target_value} (话题{s.stats['topic']}+爬楼{s.stats.get('floors', 0)})"
                            )
                        s.run = False
                        break

                    s.browse_cat(cat)

                    # 再次检查是否达到目标（browse_cat后可能已达到）
                    if s._check_target_reached():
                        if s.browse_mode == "quick":
                            s.lg(
                                f"已达到目标主题数: {s.stats.get('topic', 0)}/{s.target_value}"
                            )
                        else:
                            total_read = s.stats.get(
                                "posts_read",
                                s.stats.get("topic", 0) + s.stats.get("floors", 0),
                            )
                            s.lg(
                                f"已达到目标已读数: {total_read}/{s.target_value} (话题{s.stats['topic']}+爬楼{s.stats.get('floors', 0)})"
                            )
                        s.run = False
                        break

                    # 显示进度
                    if s.browse_mode == "quick":
                        if s.mode == "topics":
                            remaining = s.target_value - s.stats.get("topic", 0)
                            s.lg(
                                f"📊 进度: {s.stats.get('topic', 0)}/{s.target_value} 主题 (剩余 {remaining})"
                            )
                    else:
                        total_read = s.stats.get(
                            "posts_read",
                            s.stats.get("topic", 0) + s.stats.get("floors", 0),
                        )
                        if s.mode == "topics":
                            remaining = s.target_value - total_read
                            s.lg(
                                f"📊 进度: {total_read}/{s.target_value} (话题{s.stats['topic']}+爬楼{s.stats.get('floors', 0)}) 剩余 {remaining}"
                            )

                    if s.mode == "time":
                        elapsed_minutes = (time.time() - s.start_time) / 60
                        remaining_minutes = s.target_value - elapsed_minutes
                        s.lg(
                            f"⏱ 进度: {int(elapsed_minutes)}/{s.target_value} 分钟 (剩余 {int(remaining_minutes)} 分钟)"
                        )

                    # 板块之间随机等待（检查开关）
                    if s.enable_wait and s.run:
                        s._random_delay(
                            s.cfg["wait_min"] + 1, s.cfg["wait_max"] + 2, "切换板块"
                        )

                # 数量和时间模式也继续下一轮，直到达到目标或收到停止请求。
                if not s.run or s._check_target_reached():
                    break

                # 下一轮重新打乱板块顺序。
                if s.run:
                    random.shuffle(enabled)
                    s.lg("=" * 30)
                    s.lg("继续下一轮浏览...")
                    s.lg("=" * 30)

            # 计算耗时
            elapsed_time = time.time() - s.start_time
            elapsed_minutes = int(elapsed_time / 60)
            elapsed_seconds = int(elapsed_time % 60)

            # 计算已读总数
            total_read = s.stats.get(
                "posts_read", s.stats.get("topic", 0) + s.stats.get("floors", 0)
            )

            s.lg("=" * 30)
            outcome = COMPLETED if s._check_target_reached() and not s._stop_requested.is_set() else STOPPED
            s.lg("已完成目标!" if outcome == COMPLETED else "已停止")
            s.lg(f"浏览话题: {s.stats['topic']}")
            s.lg(f"浏览帖子: {s.stats.get('posts_read', total_read)}")
            s.lg(f"爬楼总数: {s.stats.get('floors', 0)} 楼")
            s.lg(f"已读总计: {total_read} (话题+爬楼)")
            s.lg(f"点赞主帖: {s.stats['like']}")
            s.lg(f"点赞回复: {s.stats['like_reply']}")
            s.lg(f"回帖数量: {s.stats['reply']}")
            s.lg(f"耗时: {elapsed_minutes} 分 {elapsed_seconds} 秒")
            s.lg("=" * 30)

            # 手动停止也要在关闭浏览器前检查最新进度；停止标记只中断浏览。
            if s.pg:
                s.lg("")
                s.lg("=" * 30)
                s.lg("重新获取等级信息验证效果...")
                final_info = s.get_level_info(is_final=True)

                # 显示真实进度变化
                if final_info and s.initial_level_info:
                    s.lg("")
                    s.lg("📊 真实进度变化（基于站点数据）:")
                    s.lg("-" * 30)
                    initial_reqs = {
                        r["name"]: r
                        for r in s.initial_level_info.get("requirements", [])
                    }
                    final_reqs = {
                        r["name"]: r for r in final_info.get("requirements", [])
                    }

                    for name, final_req in final_reqs.items():
                        if name in initial_reqs:
                            try:
                                initial_val = int(
                                    initial_reqs[name]["current"].replace(",", "")
                                )
                                final_val = int(final_req["current"].replace(",", ""))
                                change = final_val - initial_val
                                change_str = (
                                    f"+{change}" if change >= 0 else str(change)
                                )
                                s.lg(
                                    f"  {name}: {initial_val} → {final_val} ({change_str})"
                                )
                            except:
                                s.lg(
                                    f"  {name}: {initial_reqs[name]['current']} → {final_req['current']}"
                                )
                    s.lg("-" * 30)

                s.lg("=" * 30)

            return outcome
        finally:
            s.run = False
            if browser_started:
                s.close()


class GUI:
    def __init__(s):
        s.rt = tk.Tk()
        s.screen_height = s.rt.winfo_screenheight()
        s.rt.title(f"Linux.do 刷帖助手 v{VERSION}")
        # Keep the statistics section visible on typical displays while leaving
        # enough room for the system title bar and taskbar on smaller screens.
        available_height = max(600, s.screen_height - 80)
        initial_height = min(1050, available_height)
        minimum_height = min(900, max(560, available_height - 20))
        available_width = max(950, s.rt.winfo_screenwidth() - 80)
        initial_width = min(1060, available_width)
        minimum_width = min(980, available_width)
        s.rt.geometry(f"{initial_width}x{initial_height}")
        s.rt.minsize(minimum_width, minimum_height)  # 设置最小窗口大小
        s.rt.configure(bg="#1a1a2e")

        # 设置窗口图标
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                s.rt.iconbitmap(icon_path)
        except:
            pass

        # 不使用overrideredirect，保留系统标题栏以支持窗口拉伸
        # s.rt.overrideredirect(True)  # 移除默认标题栏

        # 每个 GUI 实例使用独立的默认状态，避免共享嵌套配置对象。
        s.cats = default_categories()
        s.cfg = default_config()
        s.bot = None
        s.th = None
        s.task_registry = TaskRegistry()
        s.browser_entries = {"bitbrowser": [], "simprint": []}
        s.browser_tables = {}
        s._closing = False
        s.req_labels = {}  # 升级要求标签
        s.initial_requirements = []  # 初始升级要求

        # 窗口拖动相关（保留以备后用）
        s._drag_x = 0
        s._drag_y = 0

        # 托盘相关
        s.tray_icon = None
        s.tray_thread = None
        s._running_status = "就绪"

        s._ui()

        # 应用上次保存的配置
        s._apply_settings(s._load_settings())

        # 同步浏览器后端选择对应的参数显示
        s._on_backend_toggle()

        # 任何配置变化即时落盘（在应用已保存配置之后挂载，避免恢复时反复写盘）
        s._install_autosave()

        # 窗口居中
        s._center_window()

        # 初始化托盘
        if TRAY_SUPPORT:
            s._init_tray()

        # 窗口关闭时的处理
        s.rt.protocol("WM_DELETE_WINDOW", s._on_close_window)

        # 启动后检查更新（延迟执行，避免阻塞UI）
        s.rt.after(1000, s._check_update)

    def _settings_var_map(s):
        """配置项 -> 对应的 Tk 变量（UI 原始值，读写对称）"""
        return {
            "mode": s.mode_var,
            "topics": s.topics_var,
            "time": s.time_var,
            "browse_mode": s.browse_mode_var,
            "proxy": s.proxy_var,
            "enable_like": s.enable_like_var,
            "like": s.like_var,
            "enable_reply": s.enable_reply_var,
            "reply": s.reply_var,
            "enable_wait": s.enable_wait_var,
            "wait": s.wait_var,
            "reply_count_min": s.reply_count_min_var,
            "reply_count_max": s.reply_count_max_var,
            "unread_only": s.unread_only_var,
            "list_scroll": s.list_scroll_var,
            "browser_backend": s.browser_backend_var,
            "bit_api_port": s.bit_port_var,
            "bit_window_id": s.bit_id_var,
            "simprint_api_port": s.simprint_port_var,
            "simprint_api_key": s.simprint_key_var,
            "simprint_env_uuid": s.simprint_env_var,
        }

    def _load_settings(s):
        """从磁盘读取配置；文件不存在或损坏时返回空字典"""
        try:
            with open(get_settings_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _apply_settings(s, data):
        """把读到的配置应用到 UI 控件（须在 _ui 之后调用）"""
        if not data:
            return
        s.task_registry.restore(data.get("browser_tasks"))
        for key, var in s._settings_var_map().items():
            if key in data:
                try:
                    var.set(data[key])
                except Exception:
                    pass
        cats = data.get("cats")
        if isinstance(cats, dict):
            for cat in s.cats:
                if cat["n"] in cats:
                    cat["e"] = bool(cats[cat["n"]])
                    if cat["n"] in s.cat_vars:
                        s.cat_vars[cat["n"]].set(cat["e"])

        # 新格式按 ID 保存行，兼容旧版以显示名称为键的列表配置。
        for backend, prefix, id_var in (
            ("bitbrowser", "bit_window", s.bit_id_var),
            ("simprint", "simprint_env", s.simprint_env_var),
        ):
            if prefix + "_entries" not in data and prefix + "_options" not in data:
                continue
            entries = data.get(prefix + "_entries")
            old_options = data.get(prefix + "_options", {})
            if not isinstance(old_options, dict):
                old_options = {}
            if not isinstance(entries, list):
                entries = []
                for label, entry_id in old_options.items():
                    if not label or not entry_id:
                        continue
                    if backend == "bitbrowser":
                        label = migrate_bitbrowser_window_label(label, entry_id)
                    elif data.get("simprint_env_label_format") != "name":
                        label = migrate_simprint_env_label(label)
                    entries.append({"id": str(entry_id), "name": label})
            selected_id = id_var.get().strip()
            if selected_id not in {entry["id"] for entry in normalize_entries(entries)}:
                selected_id = str(old_options.get(data.get(prefix + "_selection")) or "")
            s._set_browser_entries(backend, entries, selected_id)
        s._refresh_task_tables()

    def _collect_settings(s):
        """收集当前 UI 控件的值，用于写盘"""
        data = {key: var.get() for key, var in s._settings_var_map().items()}
        data["cats"] = {
            cat["n"]: bool(s.cat_vars[cat["n"]].get())
            for cat in s.cats
            if cat["n"] in s.cat_vars
        }
        data["bit_window_options"] = dict(s.bit_window_options)
        data["bit_window_selection"] = s.bit_window_select_var.get()
        data["simprint_env_options"] = dict(s.simprint_env_options)
        data["simprint_env_selection"] = s.simprint_env_select_var.get()
        data["simprint_env_label_format"] = "name"
        data["bit_window_entries"] = deepcopy(s.browser_entries["bitbrowser"])
        data["simprint_env_entries"] = deepcopy(s.browser_entries["simprint"])
        data["browser_tasks"] = s.task_registry.snapshot()
        return data

    def _save_settings(s):
        """把当前 UI 配置写入磁盘（原子写，避免写到一半被中断而损坏）"""
        try:
            path = get_settings_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(s._collect_settings(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass

    def _install_autosave(s):
        """给所有配置控件挂上「变化即保存」回调，避免依赖开始/关闭时机"""
        for var in s._settings_var_map().values():
            try:
                var.trace_add("write", lambda *a: s._save_settings())
            except Exception:
                pass

    def _check_update(s):
        """检查版本更新"""

        def check():
            try:
                # 获取 GitHub Releases 最新版本
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "LinuxDoHelper"}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    latest_version = data.get("tag_name", "").lstrip("v")
                    release_url = data.get("html_url", "")

                    # 比较版本号
                    if (
                        latest_version
                        and s._compare_versions(latest_version, VERSION) > 0
                    ):
                        # 有新版本，在主线程显示提示
                        s.rt.after(
                            0,
                            lambda: s._show_update_dialog(latest_version, release_url),
                        )
            except Exception as e:
                # 网络错误等，静默忽略
                pass

        # 在后台线程执行检查
        threading.Thread(target=check, daemon=True).start()

    def _compare_versions(s, v1, v2):
        """比较版本号，返回 1 表示 v1 > v2，-1 表示 v1 < v2，0 表示相等"""
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]

            # 补齐长度
            while len(parts1) < len(parts2):
                parts1.append(0)
            while len(parts2) < len(parts1):
                parts2.append(0)

            for p1, p2 in zip(parts1, parts2):
                if p1 > p2:
                    return 1
                elif p1 < p2:
                    return -1
            return 0
        except:
            return 0

    def _show_update_dialog(s, latest_version, release_url):
        """显示更新提示对话框"""
        result = messagebox.askyesno(
            "发现新版本",
            f"🎉 发现新版本 v{latest_version}\n\n"
            f"当前版本: v{VERSION}\n"
            f"最新版本: v{latest_version}\n\n"
            "是否打开下载页面？",
            icon="info",
        )
        if result and release_url:
            import webbrowser

            webbrowser.open(release_url)

    def _init_tray(s):
        """初始化系统托盘"""
        if not TRAY_SUPPORT:
            return

        def create_menu():
            return pystray.Menu(
                pystray.MenuItem("显示窗口", s._show_window, default=True),
                pystray.MenuItem("开始运行", s._tray_start),
                pystray.MenuItem("停止运行", s._tray_stop),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", s._tray_quit),
            )

        # 创建托盘图标
        s.tray_icon = pystray.Icon(
            "LinuxDoHelper",
            create_tray_image("#0f3460"),
            "Linux.do 刷帖助手 - 就绪",
            create_menu(),
        )

        # 在后台线程运行托盘
        s.tray_thread = threading.Thread(target=s.tray_icon.run, daemon=True)
        s.tray_thread.start()

    def _update_tray_status(s, status, stats=None):
        """更新托盘状态"""
        if not TRAY_SUPPORT or not s.tray_icon:
            return

        s._running_status = status

        # 根据状态设置不同颜色
        if status == "运行中":
            color = "#00ff88"  # 绿色
        elif status == "已停止" or status == "已完成":
            color = "#ffaa00"  # 橙色
        else:
            color = "#0f3460"  # 默认蓝色

        # 更新图标
        s.tray_icon.icon = create_tray_image(color)

        # 更新提示文字
        tooltip = f"Linux.do 刷帖助手 v{VERSION} - {status}\n"

        if s.bot and s.bot.start_time:
            # 计算用时
            elapsed_time = time.time() - s.bot.start_time
            elapsed_minutes = int(elapsed_time / 60)
            elapsed_seconds = int(elapsed_time % 60)

            # 计算已读总数
            total_read = s.bot.stats.get(
                "posts_read",
                s.bot.stats.get("topic", 0) + s.bot.stats.get("floors", 0),
            )

            # 显示模式
            if s.bot.mode == "topics":
                remaining = s.bot.target_value - total_read
                tooltip += f"模式: 已读限制 (剩余 {remaining}/{s.bot.target_value})\n"
            elif s.bot.mode == "time":
                elapsed_mins = elapsed_time / 60
                remaining_mins = s.bot.target_value - elapsed_mins
                tooltip += f"模式: 时间限制 (剩余 {int(remaining_mins)}/{s.bot.target_value}分钟)\n"
            else:
                tooltip += f"模式: 无尽模式\n"

            # 显示浏览模式
            if s.bot.browse_mode == "quick":
                tooltip += f"浏览: 快速模式\n"
            else:
                tooltip += f"浏览: 深度爬楼\n"

            tooltip += f"用时: {elapsed_minutes}:{elapsed_seconds:02d}\n"

        if stats:
            total_read = stats.get(
                "posts_read", stats.get("topic", 0) + stats.get("floors", 0)
            )
            tooltip += f"已读: {total_read} (话题{stats.get('topic', 0)}+楼{stats.get('floors', 0)}) | "
            tooltip += f"点赞: {stats.get('like', 0) + stats.get('like_reply', 0)} | "
            tooltip += f"回复: {stats.get('reply', 0)}"

        s.tray_icon.title = tooltip

    def _show_window(s, icon=None, item=None):
        """显示窗口"""
        s.rt.after(0, s._do_show_window)

    def _do_show_window(s):
        """在主线程中显示窗口"""
        s.rt.deiconify()
        s.rt.lift()
        s.rt.focus_force()

    def _tray_start(s, icon=None, item=None):
        """从托盘启动"""
        s.rt.after(0, s._start)

    def _tray_stop(s, icon=None, item=None):
        """从托盘停止"""
        s.rt.after(0, s._stop)

    def _tray_quit(s, icon=None, item=None):
        """从托盘退出"""
        if s.tray_icon:
            s.tray_icon.stop()
        s.rt.after(0, s._close)

    def _on_close_window(s):
        """窗口关闭按钮处理 - 最小化到托盘"""
        s._save_settings()
        if TRAY_SUPPORT and s.tray_icon:
            s.rt.withdraw()  # 隐藏窗口
        else:
            s._close()

    def _center_window(s):
        """窗口居中显示"""
        s.rt.update_idletasks()
        w = s.rt.winfo_width()
        h = s.rt.winfo_height()
        sw = s.rt.winfo_screenwidth()
        sh = s.rt.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        s.rt.geometry(f"{w}x{h}+{x}+{y}")

    def _start_drag(s, event):
        """开始拖动窗口"""
        s._drag_x = event.x
        s._drag_y = event.y

    def _do_drag(s, event):
        """拖动窗口"""
        x = s.rt.winfo_x() + event.x - s._drag_x
        y = s.rt.winfo_y() + event.y - s._drag_y
        s.rt.geometry(f"+{x}+{y}")

    def _minimize(s):
        """最小化窗口"""
        if TRAY_SUPPORT and s.tray_icon:
            s.rt.withdraw()  # 最小化到托盘
        else:
            s.rt.iconify()

    def _on_restore(s, event):
        """恢复窗口"""
        pass  # 不再需要overrideredirect

    def _close(s):
        """关闭窗口"""
        s._closing = True
        if s.task_registry.busy:
            s._stop()
            s.status.set("正在停止并退出...")
            s._refresh_task_tables()
            return
        s._destroy_window()

    def _destroy_window(s):
        s._save_settings()
        if s.tray_icon:
            try:
                s.tray_icon.stop()
            except:
                pass
        s.rt.destroy()

    def _ui(s):
        # 状态变量（放在顶部，供其他地方使用）
        s.status = tk.StringVar(value="就绪")

        # 左侧为设置与运行信息，右侧为独立的浏览器列表区域。
        layout = tk.Frame(s.rt, bg="#1a1a2e")
        layout.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        layout.columnconfigure(0, weight=1, minsize=650)
        layout.columnconfigure(1, weight=0)
        layout.rowconfigure(0, weight=1)

        content = tk.Frame(layout, bg="#1a1a2e")
        content.grid(row=0, column=0, sticky="nsew")

        s.browser_list_panel = tk.LabelFrame(
            layout,
            text=" 浏览器列表 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.browser_list_panel.grid(
            row=0, column=1, sticky="nsew", padx=(0, 15), pady=5
        )
        s.browser_list_panel.bind("<Configure>", s._fit_window_to_browser_list)
        s.bit_list_frame = tk.Frame(s.browser_list_panel, bg="#1a1a2e")
        s.simprint_list_frame = tk.Frame(s.browser_list_panel, bg="#1a1a2e")

        # 信息展示容器，仅放置升级进度的显示开关。
        display_frame = tk.LabelFrame(
            content,
            text=" 信息展示 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        display_frame.pack(fill=tk.X, padx=15, pady=5)

        s.progress_expanded_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            display_frame,
            text="显示升级进度",
            variable=s.progress_expanded_var,
            command=s._toggle_progress_panel,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
            activeforeground="#ffffff",
        ).pack(anchor="e", padx=10, pady=(2, 0))

        # 用户信息栏
        info_frame = tk.LabelFrame(
            content,
            text=" 用户信息 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        info_frame.pack(fill=tk.X, padx=15, pady=5)

        info_inner = tk.Frame(info_frame, bg="#1a1a2e")
        info_inner.pack(fill=tk.X, padx=10, pady=5)

        s.user_label = tk.StringVar(value="用户: 未登录")
        s.level_label = tk.StringVar(value="等级: -")
        s.next_level_label = tk.StringVar(value="下一级: -")

        tk.Label(
            info_inner,
            textvariable=s.user_label,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            info_inner,
            textvariable=s.level_label,
            bg="#1a1a2e",
            fg="#00ff88",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            info_inner,
            textvariable=s.next_level_label,
            bg="#1a1a2e",
            fg="#ffaa00",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)

        # 升级进度面板（使用固定高度的Canvas实现滚动）
        progress_frame = tk.LabelFrame(
            content,
            text=" 升级进度追踪 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.progress_frame = progress_frame
        # 默认关闭时不显示整个升级进度区域。

        s.progress_content = tk.Frame(progress_frame, bg="#1a1a2e")

        # 创建Canvas和滚动条
        s.progress_canvas = tk.Canvas(
            s.progress_content, bg="#1a1a2e", height=200, highlightthickness=0
        )
        s.progress_inner = tk.Frame(s.progress_canvas, bg="#1a1a2e")

        s.progress_inner.bind(
            "<Configure>",
            lambda e: s.progress_canvas.configure(
                scrollregion=s.progress_canvas.bbox("all")
            ),
        )

        s.progress_canvas.create_window((0, 0), window=s.progress_inner, anchor="nw")
        s.progress_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        s.progress_canvas.bind("<MouseWheel>", lambda e: s.progress_canvas.yview_scroll(int(-e.delta / 120), "units"))
        s.progress_content.pack(fill=tk.X, padx=5, pady=(0, 5))

        # 运行模式选择
        mode_frame = tk.LabelFrame(
            content,
            text=" 运行模式 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        mode_frame.pack(fill=tk.X, padx=15, pady=5)
        # 记录进度面板的插入位置，重新显示时仍位于运行模式之前。
        s.progress_insert_before = mode_frame

        mode_inner = tk.Frame(mode_frame, bg="#1a1a2e")
        mode_inner.pack(fill=tk.X, padx=10, pady=8)

        s.mode_var = tk.StringVar(value="endless")

        # 无尽模式
        tk.Radiobutton(
            mode_inner,
            text="无尽模式",
            variable=s.mode_var,
            value="endless",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        # 帖子数量模式
        tk.Radiobutton(
            mode_inner,
            text="帖子数量:",
            variable=s.mode_var,
            value="topics",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        s.topics_var = tk.StringVar(value="50")
        tk.Entry(
            mode_inner,
            textvariable=s.topics_var,
            width=8,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(
            mode_inner,
            text="个",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

        # 时间限制模式
        tk.Radiobutton(
            mode_inner,
            text="时间限制:",
            variable=s.mode_var,
            value="time",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=10)

        s.time_var = tk.StringVar(value="30")
        tk.Entry(
            mode_inner,
            textvariable=s.time_var,
            width=8,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(
            mode_inner,
            text="分钟",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

        # 浏览模式选择（第二行）
        browse_mode_inner = tk.Frame(mode_frame, bg="#1a1a2e")
        browse_mode_inner.pack(fill=tk.X, padx=10, pady=(0, 8))

        tk.Label(
            browse_mode_inner,
            text="浏览模式:",
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=(0, 10))

        s.browse_mode_var = tk.StringVar(value="deep")

        tk.Radiobutton(
            browse_mode_inner,
            text="深度爬楼（完整阅读）",
            variable=s.browse_mode_var,
            value="deep",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=5)

        tk.Radiobutton(
            browse_mode_inner,
            text="快速浏览（3-5层换帖）",
            variable=s.browse_mode_var,
            value="quick",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(
            browse_mode_inner,
            text="(快速模式增加浏览话题数)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT, padx=5)

        # 浏览器、后端参数与代理设置
        browser_network_frame = tk.LabelFrame(
            content,
            text=" 浏览器与代理 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        browser_network_frame.pack(fill=tk.X, padx=15, pady=5)

        browser_block = tk.Frame(browser_network_frame, bg="#1a1a2e", pady=3)
        browser_block.pack(fill=tk.X, padx=10, pady=(3, 0))
        browser_frame = tk.Frame(browser_block, bg="#1a1a2e")
        browser_frame.pack(fill=tk.X)
        browser_param_frame = tk.Frame(browser_block, bg="#1a1a2e")
        browser_param_frame.pack(fill=tk.X, pady=(4, 0))
        tk.Label(
            browser_frame, text="浏览器:", bg="#1a1a2e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        s.browser_backend_var = tk.StringVar(
            value=s.cfg.get("browser_backend", "builtin")
        )
        tk.Radiobutton(
            browser_frame,
            text="内置Chromium",
            variable=s.browser_backend_var,
            value="builtin",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
            command=s._on_backend_toggle,
        ).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(
            browser_frame,
            text="比特浏览器",
            variable=s.browser_backend_var,
            value="bitbrowser",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
            command=s._on_backend_toggle,
        ).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(
            browser_frame,
            text="Simprint",
            variable=s.browser_backend_var,
            value="simprint",
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#16213e",
            activebackground="#1a1a2e",
            activeforeground="#00d9ff",
            font=(FONT_FAMILY, 9),
            command=s._on_backend_toggle,
        ).pack(side=tk.LEFT, padx=5)

        # 比特浏览器参数（仅在选择比特浏览器时显示）
        s.bit_frame = tk.Frame(browser_param_frame, bg="#1a1a2e")
        s.bit_frame.pack(side=tk.LEFT, padx=5)
        bit_controls = tk.Frame(s.bit_frame, bg="#1a1a2e")
        bit_controls.pack(fill=tk.X)
        tk.Label(
            bit_controls, text="端口:", bg="#1a1a2e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        s.bit_port_var = tk.StringVar(value=str(s.cfg.get("bit_api_port", 54345)))
        tk.Entry(
            bit_controls,
            textvariable=s.bit_port_var,
            width=6,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=3)
        # 窗口 ID 仅作为内部持久化值，由窗口选择器维护。
        s.bit_id_var = tk.StringVar(value=s.cfg.get("bit_window_id", ""))
        s.bit_fetch_btn = tk.Button(
            bit_controls,
            text="获取窗口",
            command=s._on_bitbrowser_fetch_windows,
            bg="#0f3460",
            fg="#eaeaea",
            activebackground="#00d9ff",
            activeforeground="#1a1a2e",
            font=(FONT_FAMILY, 9),
            padx=8,
        )
        s.bit_fetch_btn.pack(side=tk.LEFT, padx=3)
        s.bit_window_options = {}
        s.bit_window_select_var = tk.StringVar(value="")
        s.bit_task_table = s._create_browser_table(s.bit_list_frame, "bitbrowser")

        # Simprint 参数（仅在选择 Simprint 时显示）
        s.simprint_frame = tk.Frame(browser_param_frame, bg="#1a1a2e")
        s.simprint_frame.pack(side=tk.LEFT, padx=5)
        simprint_controls = tk.Frame(s.simprint_frame, bg="#1a1a2e")
        simprint_controls.pack(fill=tk.X)
        tk.Label(
            simprint_controls, text="端口:", bg="#1a1a2e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        s.simprint_port_var = tk.StringVar(
            value=str(s.cfg.get("simprint_api_port", 8080))
        )
        tk.Entry(
            simprint_controls,
            textvariable=s.simprint_port_var,
            width=6,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=3)
        tk.Label(
            simprint_controls, text="Key:", bg="#1a1a2e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        s.simprint_key_var = tk.StringVar(value=s.cfg.get("simprint_api_key", ""))
        tk.Entry(
            simprint_controls,
            textvariable=s.simprint_key_var,
            width=22,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
            show="*",
        ).pack(side=tk.LEFT, padx=3)
        # 环境 UUID 仅作为内部持久化值，由环境列表维护。
        s.simprint_env_var = tk.StringVar(value=s.cfg.get("simprint_env_uuid", ""))
        s.simprint_fetch_btn = tk.Button(
            simprint_controls,
            text="获取环境",
            command=s._on_simprint_fetch_envs,
            bg="#0f3460",
            fg="#eaeaea",
            activebackground="#00d9ff",
            activeforeground="#1a1a2e",
            font=(FONT_FAMILY, 9),
            padx=8,
        )
        s.simprint_fetch_btn.pack(side=tk.LEFT, padx=3)
        s.simprint_env_options = {}
        s.simprint_env_select_var = tk.StringVar(value="")
        s.simprint_task_table = s._create_browser_table(s.simprint_list_frame, "simprint")

        # 代理和运行控制与浏览器参数共用第二行。
        s.proxy_frame = tk.Frame(browser_param_frame, bg="#1a1a2e")
        s.proxy_frame.pack(side=tk.LEFT)
        tk.Label(s.proxy_frame, text="代理:", bg="#1a1a2e", fg="#eaeaea").pack(side=tk.LEFT)
        s.proxy_var = tk.StringVar(value=s.cfg["proxy"])
        tk.Entry(
            s.proxy_frame,
            textvariable=s.proxy_var,
            width=18,
            bg="#16213e",
            fg="#eaeaea",
            insertbackground="#eaeaea",
        ).pack(side=tk.LEFT, padx=5)

        s.start_btn = tk.Button(
            browser_param_frame,
            text="开始",
            command=s._start,
            width=10,
            bg="#0f3460",
            fg="white",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.start_btn.pack(side=tk.LEFT, padx=10)
        s.stop_btn = tk.Button(
            browser_param_frame,
            text="停止",
            command=s._stop,
            width=8,
            bg="#e94560",
            fg="white",
            state=tk.DISABLED,
        )
        s.stop_btn.pack(side=tk.LEFT)

        # 倒计时使用第一行的剩余空间。
        s.countdown_var = tk.StringVar(value="")
        s.countdown_label = tk.Label(
            browser_frame,
            textvariable=s.countdown_var,
            width=1,
            anchor=tk.W,
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        s.countdown_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        # 主区域
        main = tk.Frame(content, bg="#1a1a2e")
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=(10, 5))

        # 左侧 - 板块选择
        left = tk.LabelFrame(
            main,
            text=" 板块选择 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        s.cat_vars = {}
        for cat in s.cats:
            var = tk.BooleanVar(value=cat.get("e", True))
            s.cat_vars[cat["n"]] = var
            cb = tk.Checkbutton(
                left,
                text=cat["n"],
                variable=var,
                bg="#1a1a2e",
                fg="#eaeaea",
                selectcolor="#0f3460",
                activebackground="#1a1a2e",
                command=lambda n=cat["n"], v=var: s._toggle_cat(n, v),
            )
            cb.pack(anchor=tk.W, pady=1)

        # 右侧
        right = tk.Frame(main, bg="#1a1a2e")
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 日志区域
        tk.Label(
            right,
            text="运行日志",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(anchor=tk.W)
        s.log = tk.Text(
            right,
            height=14,
            bg="#16213e",
            fg="#eaeaea",
            font=(FONT_MONO, 9),
            insertbackground="#eaeaea",
        )
        s.log.pack(fill=tk.BOTH, expand=True, pady=5)
        s.log.bind("<MouseWheel>", lambda e: s.log.yview_scroll(int(-e.delta / 120), "units"))
        s.log.config(state=tk.DISABLED)

        # 参数设置
        param = tk.LabelFrame(
            right,
            text=" 参数设置 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
            padx=8,
            pady=4,
        )
        param.pack(fill=tk.X, pady=5)

        # 第一行：点赞率和回复率
        param_row1 = tk.Frame(param, bg="#1a1a2e")
        param_row1.pack(fill=tk.X, pady=2)

        # 自动点赞开关（默认关闭）
        s.enable_like_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            param_row1,
            text="自动点赞",
            variable=s.enable_like_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row1, text="点赞率:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.like_var = tk.StringVar(value="30")
        tk.Entry(
            param_row1, textvariable=s.like_var, width=4, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row1, text="%", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(0, 15)
        )

        # 自动回复开关（默认关闭）
        s.enable_reply_var = tk.BooleanVar(value=False)
        s.reply_checkbox = tk.Checkbutton(
            param_row1,
            text="自动回复",
            variable=s.enable_reply_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
            command=s._on_reply_toggle,
        )
        s.reply_checkbox.pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row1, text="回复率:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.reply_var = tk.StringVar(value="5")
        tk.Entry(
            param_row1, textvariable=s.reply_var, width=4, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row1, text="%", bg="#1a1a2e", fg="#eaeaea").pack(side=tk.LEFT)

        # 第二行：等待时间
        param_row2 = tk.Frame(param, bg="#1a1a2e")
        param_row2.pack(fill=tk.X, pady=2)

        # 等待时间开关
        s.enable_wait_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            param_row2,
            text="启用等待",
            variable=s.enable_wait_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(param_row2, text="等待:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.wait_var = tk.StringVar(value="1-3")
        tk.Entry(
            param_row2, textvariable=s.wait_var, width=6, bg="#16213e", fg="#eaeaea"
        ).pack(side=tk.LEFT)
        tk.Label(param_row2, text="秒", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        tk.Label(
            param_row2,
            text="(已有滚动延迟，可关闭)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

        # 第三行：回复数范围
        param_row3 = tk.Frame(param, bg="#1a1a2e")
        param_row3.pack(fill=tk.X, pady=2)

        tk.Label(param_row3, text="回复数范围:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT
        )
        s.reply_count_min_var = tk.StringVar(
            value=str(s.cfg.get("reply_count_min", 0))
        )
        tk.Entry(
            param_row3,
            textvariable=s.reply_count_min_var,
            width=5,
            bg="#16213e",
            fg="#eaeaea",
        ).pack(side=tk.LEFT, padx=(5, 2))
        tk.Label(param_row3, text="-", bg="#1a1a2e", fg="#eaeaea").pack(side=tk.LEFT)
        s.reply_count_max_var = tk.StringVar(
            value=str(s.cfg.get("reply_count_max", 120))
        )
        tk.Entry(
            param_row3,
            textvariable=s.reply_count_max_var,
            width=5,
            bg="#16213e",
            fg="#eaeaea",
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(param_row3, text="条", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        tk.Label(
            param_row3,
            text="(最大留空=不限，默认0-120)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

        # 第四行：话题选择策略
        param_row4 = tk.Frame(param, bg="#1a1a2e")
        param_row4.pack(fill=tk.X, pady=2)

        s.unread_only_var = tk.BooleanVar(value=s.cfg.get("unread_only", True))
        tk.Checkbutton(
            param_row4,
            text="只浏览未读话题",
            variable=s.unread_only_var,
            bg="#1a1a2e",
            fg="#eaeaea",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(
            param_row4,
            text="(避免已读帖直接跳到末楼)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

        tk.Label(param_row4, text="列表下滑:", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(15, 2)
        )
        s.list_scroll_var = tk.StringVar(value=str(s.cfg.get("list_scroll_times", 3)))
        tk.Entry(
            param_row4,
            textvariable=s.list_scroll_var,
            width=4,
            bg="#16213e",
            fg="#eaeaea",
        ).pack(side=tk.LEFT)
        tk.Label(param_row4, text="次", bg="#1a1a2e", fg="#eaeaea").pack(
            side=tk.LEFT, padx=(2, 5)
        )
        tk.Label(
            param_row4,
            text="(找不到足够话题时加载更多)",
            bg="#1a1a2e",
            fg="#888888",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT)

        # 统计信息
        stats_frame = tk.LabelFrame(
            right,
            text=" 本次统计 ",
            bg="#1a1a2e",
            fg="#00d9ff",
            font=(FONT_FAMILY, 10, "bold"),
        )
        stats_frame.pack(fill=tk.X, pady=(5, 0))

        stats_inner = tk.Frame(stats_frame, bg="#1a1a2e")
        stats_inner.pack(fill=tk.X, padx=10, pady=(5, 15))

        s.stats_topic = tk.StringVar(value="话题: 0")
        s.stats_floors = tk.StringVar(value="爬楼: 0")
        s.stats_total = tk.StringVar(value="已读: 0")
        s.stats_like = tk.StringVar(value="点赞: 0")
        s.stats_reply = tk.StringVar(value="回复: 0")

        tk.Label(
            stats_inner,
            textvariable=s.stats_topic,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_floors,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_total,
            bg="#1a1a2e",
            fg="#00ff88",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_like,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)
        tk.Label(
            stats_inner,
            textvariable=s.stats_reply,
            bg="#1a1a2e",
            fg="#eaeaea",
            font=(FONT_FAMILY, 10),
        ).pack(side=tk.LEFT, padx=10)

    def _toggle_cat(s, name, var):
        for cat in s.cats:
            if cat["n"] == name:
                cat["e"] = var.get()
                break
        s._save_settings()

    def _create_browser_table(s, parent, backend):
        table = BrowserTaskTable(
            parent, backend, FONT_FAMILY,
            on_select=lambda entry_id: s._on_browser_select(backend, entry_id),
            on_start=lambda entry_id: s._start_browser_task(backend, entry_id),
            on_stop=lambda entry_id: s._stop_browser_task(backend, entry_id),
            on_complete=lambda entry_id: s._complete_browser_task(backend, entry_id),
        )
        table.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        s.browser_tables[backend] = table
        return table

    def _fit_window_to_browser_list(s, event=None):
        """为按内容伸缩的列表保留空间，同时保证左侧设置区域可用。"""
        layout = s.browser_list_panel.master
        left_minimum = int(layout.columnconfigure(0)["minsize"])
        list_column_width = layout.grid_bbox(1, 0)[2]
        # 外层布局左右各留有 2 像素空隙。
        minimum_width = left_minimum + list_column_width + 4
        current_minimum, minimum_height = s.rt.minsize()
        if minimum_width != current_minimum:
            s.rt.minsize(minimum_width, minimum_height)

    def _set_browser_entries(s, backend, entries, selected_id=""):
        entries = normalize_entries(entries)
        # 刷新期间仍保留正在运行的行，以便停止或完成该任务。
        present = {entry["id"] for entry in entries}
        for entry in s.browser_entries[backend]:
            if task_key(backend, entry["id"]) == s.task_registry.active_key and entry["id"] not in present:
                entries.append(dict(entry))
        s.browser_entries[backend] = entries
        options = {entry["name"]: entry["id"] for entry in entries}
        if backend == "bitbrowser":
            s.bit_window_options = options
        else:
            s.simprint_env_options = options
        if selected_id not in {entry["id"] for entry in entries}:
            selected_id = entries[0]["id"] if entries else ""
        s.browser_tables[backend].set_entries(entries, selected_id)
        s._on_browser_select(backend, selected_id, save=False)
        s._refresh_task_tables()

    def _on_browser_select(s, backend, entry_id, save=True):
        name = next((entry["name"] for entry in s.browser_entries[backend] if entry["id"] == entry_id), "")
        if backend == "bitbrowser":
            s.bit_window_select_var.set(name)
            s.bit_id_var.set(entry_id)
        else:
            s.simprint_env_select_var.set(name)
            s.simprint_env_var.set(entry_id)
        s._refresh_task_tables()
        if save:
            s._save_settings()

    def _refresh_task_tables(s):
        for table in s.browser_tables.values():
            table.render_states(s.task_registry)
        backend = s.browser_backend_var.get()
        table = s.browser_tables.get(backend)
        can_start = not s.task_registry.busy and not s._closing and (table is None or bool(table.selected_id))
        can_stop = s.task_registry.busy and s.task_registry.get(s.task_registry.active_key)["status"] == RUNNING
        s.start_btn.config(state=tk.NORMAL if can_start else tk.DISABLED)
        s.stop_btn.config(state=tk.NORMAL if can_stop else tk.DISABLED)

    def _start_browser_task(s, backend, entry_id):
        if s.task_registry.busy or s._closing or (s.th and s.th.is_alive()):
            return False
        if entry_id not in {entry["id"] for entry in s.browser_entries[backend]}:
            return False
        s.browser_backend_var.set(backend)
        s._on_backend_toggle()
        s.browser_tables[backend].select(entry_id, notify=True)
        return s._start()

    def _stop_browser_task(s, backend, entry_id):
        if task_key(backend, entry_id) == s.task_registry.active_key:
            s._stop()

    def _complete_browser_task(s, backend, entry_id):
        if entry_id not in {entry["id"] for entry in s.browser_entries[backend]}:
            return
        key = task_key(backend, entry_id)
        if key == s.task_registry.active_key:
            if not s.task_registry.request_stop(key, complete=True):
                return
            s.bot.stop()
            s.status.set("正在完成...")
            s._update_tray_status("正在完成", s.bot.stats)
        elif not s.task_registry.mark_complete(key):
            return
        s._refresh_task_tables()
        s._save_settings()

    def _on_backend_toggle(s):
        """同步左侧浏览器参数和右侧对应的单选列表。"""
        backend = s.browser_backend_var.get()
        s.bit_frame.pack_forget()
        s.simprint_frame.pack_forget()
        s.bit_list_frame.pack_forget()
        s.simprint_list_frame.pack_forget()
        s.proxy_frame.pack_forget()
        if backend == "bitbrowser":
            s.bit_frame.pack(side=tk.LEFT, padx=5, before=s.start_btn)
            s.bit_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            s.browser_list_panel.config(text=" 比特浏览器窗口 ")
        elif backend == "simprint":
            s.simprint_frame.pack(side=tk.LEFT, padx=5, before=s.start_btn)
            s.simprint_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            s.browser_list_panel.config(text=" Simprint 环境 ")
        else:
            s.proxy_frame.pack(side=tk.LEFT, before=s.start_btn)
            s.browser_list_panel.config(text=" 浏览器列表 ")
        s._refresh_task_tables()

    def _bitbrowser_api_params_from_ui(s):
        try:
            port = int(s.bit_port_var.get())
            if port <= 0 or port > 65535:
                raise ValueError
        except Exception:
            port = 54345
            s.bit_port_var.set(str(port))
        return port

    def _load_bitbrowser_windows(s, port):
        """通过比特浏览器本地 API 分页读取窗口列表。"""
        # BitBrowser 文档规定分页从 0 开始，page=0 才是第一页。
        page = 0
        page_size = 100
        windows = []

        while True:
            resp = call_bitbrowser_api(
                port,
                "/browser/list",
                {"page": page, "pageSize": page_size},
                timeout=20,
            )
            if (
                not isinstance(resp, dict)
                or resp.get("success") is False
                or resp.get("code") in (0, False)
            ):
                message = resp.get("msg") or resp.get("message") if resp else "无响应"
                raise RuntimeError(message)

            page_windows = extract_bitbrowser_windows(resp)
            windows.extend(page_windows)
            data = resp.get("data", {}) or {}
            if isinstance(data, list):
                raw_items = data
                total = resp.get("total")
            elif isinstance(data, dict):
                raw_items = next(
                    (
                        data.get(key)
                        for key in (
                            "list",
                            "items",
                            "browserList",
                            "browser_list",
                            "windows",
                            "data",
                        )
                        if isinstance(data.get(key), list)
                    ),
                    [],
                )
                total = data.get("total")
            else:
                break

            if isinstance(total, int):
                if (page + 1) * page_size < total:
                    page += 1
                    continue
                break
            if len(raw_items) >= page_size:
                page += 1
                continue
            break

        unique = {}
        for window in windows:
            unique.setdefault(window["id"], window)
        return list(unique.values())

    def _on_bitbrowser_fetch_windows(s):
        port = s._bitbrowser_api_params_from_ui()
        s.bit_fetch_btn.config(state=tk.DISABLED, text="获取中...")

        def worker():
            try:
                windows = s._load_bitbrowser_windows(port)
                s.rt.after(0, lambda: s._finish_bitbrowser_fetch(windows, None))
            except Exception as e:
                s.rt.after(0, lambda error=e: s._finish_bitbrowser_fetch([], error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_bitbrowser_fetch(s, windows, error):
        s.bit_fetch_btn.config(state=tk.NORMAL, text="获取窗口")
        if error:
            messagebox.showerror("错误", f"获取比特浏览器窗口失败：{error}")
            return
        if not windows:
            s._set_browser_entries("bitbrowser", [])
            s._save_settings()
            messagebox.showinfo("未找到窗口", "比特浏览器 API 没有返回可用窗口")
            return

        s._set_browser_entries(
            "bitbrowser",
            [{"id": window["id"], "name": format_bitbrowser_window_label(window)} for window in windows],
            s.bit_id_var.get().strip(),
        )
        s._save_settings()

    def _simprint_api_params_from_ui(s):
        try:
            port = int(s.simprint_port_var.get())
        except Exception:
            port = 8080
            s.simprint_port_var.set(str(port))
        api_key = s.simprint_key_var.get().strip()
        if not api_key:
            messagebox.showerror("错误", "请先填写 Simprint API Key")
            return None
        return port, api_key

    def _load_linuxdo_simprint_envs(s, port, api_key):
        page = 1
        page_size = 100
        environments = []

        while True:
            payload = {"page": page, "page_size": page_size}
            resp = call_simprint_api(
                port,
                api_key,
                "/environments/list",
                payload,
                timeout=20,
            )
            if not resp or resp.get("code") != 1:
                msg = resp.get("message") or resp.get("msg") if resp else "无响应"
                raise RuntimeError(msg)

            data = resp.get("data", {}) or {}
            items = data.get("items", []) or []
            environments.extend(extract_linuxdo_simprint_environments(resp))

            total = data.get("total")
            if isinstance(total, int):
                if page * page_size >= total:
                    break
            elif len(items) < page_size:
                break
            page += 1

        return environments

    def _on_simprint_fetch_envs(s):
        params = s._simprint_api_params_from_ui()
        if not params:
            return
        port, api_key = params
        s.simprint_fetch_btn.config(state=tk.DISABLED, text="获取中...")

        def worker():
            try:
                environments = s._load_linuxdo_simprint_envs(port, api_key)
                s.rt.after(0, lambda: s._finish_simprint_fetch_envs(environments, None))
            except Exception as e:
                s.rt.after(0, lambda error=e: s._finish_simprint_fetch_envs([], error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_simprint_fetch_envs(s, environments, error):
        s.simprint_fetch_btn.config(state=tk.NORMAL, text="获取环境")
        if error:
            messagebox.showerror("错误", f"获取 Simprint 环境失败：{error}")
            return
        if not environments:
            s._set_browser_entries("simprint", [])
            s._save_settings()
            messagebox.showinfo(
                "未找到环境",
                "未找到分组名为 linuxdo / Linuxdo / linux.do / Linux.do 的 Simprint 环境",
            )
            return

        s._set_browser_entries(
            "simprint",
            [{"id": env["uuid"], "name": env["name"]} for env in environments],
            s.simprint_env_var.get().strip(),
        )
        s._save_settings()
        messagebox.showinfo("完成", f"找到 {len(s.browser_entries['simprint'])} 个 Linux.do 分组环境")

    def _on_reply_toggle(s):
        """自动回复开关切换时的处理"""
        if s.enable_reply_var.get():
            # 用户启用了自动回复，显示风险提醒
            result = messagebox.askokcancel(
                "风险提醒",
                "⚠️ 自动回复功能风险提示\n\n"
                "据社区反馈，L站可能存在检测自动回复的机制：\n"
                "• 曾有用户因自动回复被举报\n"
                "• 可能影响账号信任等级\n"
                "• 建议仅在必要时谨慎使用\n\n"
                "是否确定要启用自动回复功能？",
                icon="warning",
            )
            if not result:
                # 用户取消，恢复为未选中状态
                s.enable_reply_var.set(False)

    def _update_info(s, info, is_final=False):
        """更新用户信息显示"""

        def update():
            if info.get("username"):
                s.user_label.set("用户: " + info["username"])
            if info.get("level"):
                s.level_label.set("等级: " + info["level"] + "级")
            if info.get("nextLevel"):
                s.next_level_label.set("下一级: " + info["nextLevel"] + "级")

            # 更新升级进度面板
            requirements = info.get("requirements", [])
            if requirements:
                if not s.initial_requirements:
                    # 首次获取，保存初始值
                    s.initial_requirements = requirements.copy()
                    s._build_progress_panel(requirements)
                elif is_final:
                    # 结束时更新，显示实际变化
                    s._update_final_progress(requirements)

        s.rt.after(0, update)

    def _update_final_progress(s, new_requirements):
        """结束时更新进度面板，显示实际变化"""
        for new_req in new_requirements:
            name = new_req.get("name", "")
            new_current = new_req.get("current", "0")

            if name in s.req_labels:
                labels = s.req_labels[name]
                try:
                    initial = int(labels["initial"].replace(",", ""))
                    new_val = int(new_current.replace(",", ""))
                    actual_added = new_val - initial

                    labels["current_var"].set(new_current)
                    if actual_added > 0:
                        labels["added_var"].set(f"+{actual_added}")
                    elif actual_added < 0:
                        labels["added_var"].set(str(actual_added))
                    else:
                        labels["added_var"].set("+0")
                except:
                    labels["current_var"].set(new_current)

    def _toggle_progress_panel(s):
        """显示或隐藏整个升级进度区域，保留内部控件以支持后台更新。"""
        s.progress_expanded = bool(s.progress_expanded_var.get())
        if s.progress_expanded:
            s.progress_frame.pack(
                fill=tk.X, padx=15, pady=5, before=s.progress_insert_before
            )
        else:
            s.progress_frame.pack_forget()

    def _build_progress_panel(s, requirements):
        """构建升级进度面板"""
        # 清除旧内容
        for widget in s.progress_inner.winfo_children():
            widget.destroy()
        s.req_labels = {}

        # 创建表格头
        headers = ["指标", "初始值", "当前值", "目标值", "本次+"]
        # 列宽设置为0表示自动适应内容宽度
        col_widths = [0, 0, 0, 0, 0]
        # 每列的左右间距 (padx)
        col_padx = [(10, 20), (10, 20), (10, 15), (10, 15), (10, 10)]

        for col, header in enumerate(headers):
            tk.Label(
                s.progress_inner,
                text=header,
                bg="#1a1a2e",
                fg="#00d9ff",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=0, column=col, padx=col_padx[col], pady=5, sticky="w")

        # 创建数据行
        for row, req in enumerate(requirements[:8], start=1):
            name = req.get("name", "")
            current = req.get("current", "0")
            required = req.get("required", "0")

            # 指标名
            tk.Label(
                s.progress_inner,
                text=name,
                bg="#1a1a2e",
                fg="#eaeaea",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=0, padx=col_padx[0], pady=3, sticky="w")

            # 初始值
            tk.Label(
                s.progress_inner,
                text=current,
                bg="#1a1a2e",
                fg="#888888",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=1, padx=col_padx[1], pady=3, sticky="w")

            # 当前值（可更新）
            current_var = tk.StringVar(value=current)
            tk.Label(
                s.progress_inner,
                textvariable=current_var,
                bg="#1a1a2e",
                fg="#00ff88",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=row, column=2, padx=col_padx[2], pady=3, sticky="w")

            # 目标值
            tk.Label(
                s.progress_inner,
                text=required,
                bg="#1a1a2e",
                fg="#ffaa00",
                font=(FONT_FAMILY, 9),
                anchor="w",
            ).grid(row=row, column=3, padx=col_padx[3], pady=3, sticky="w")

            # 本次增加
            added_var = tk.StringVar(value="+0")
            tk.Label(
                s.progress_inner,
                textvariable=added_var,
                bg="#1a1a2e",
                fg="#00d9ff",
                font=(FONT_FAMILY, 9, "bold"),
                anchor="w",
            ).grid(row=row, column=4, padx=col_padx[4], pady=3, sticky="w")

            # 保存引用
            s.req_labels[name] = {
                "initial": current,
                "current_var": current_var,
                "added_var": added_var,
            }

    def _update_progress(s, stats):
        """根据统计更新进度显示"""

        def update():
            if not s.req_labels:
                return

            # 根据统计数据更新相关指标
            for name, labels in s.req_labels.items():
                try:
                    initial = int(labels["initial"].replace(",", ""))
                    added = 0

                    # 按具体指标映射统计，避免浏览话题和浏览帖子共用一个值。
                    added = progress_added_for_metric(name, stats)
                    if added is None:
                        continue

                    if added > 0:
                        new_val = initial + added
                        labels["current_var"].set(str(new_val))
                        labels["added_var"].set(f"+{added}")
                except:
                    pass

            # 更新托盘状态（实时显示统计）
            if s.task_registry.busy:
                active_status = s.task_registry.get(s.task_registry.active_key)["status"]
                s._update_tray_status(STATUS_LABELS[active_status], stats)

        s.rt.after(0, update)

    def _update_countdown(s, text):
        """更新倒计时显示"""

        def update():
            s.countdown_var.set(text)

        s.rt.after(0, update)

    def _lg(s, msg):
        def log():
            ts = datetime.now().strftime("%H:%M:%S")
            s.log.config(state=tk.NORMAL)
            s.log.insert(tk.END, "[" + ts + "] " + msg + "\n")
            s.log.see(tk.END)
            s.log.config(state=tk.DISABLED)

            # 更新统计
            if s.bot:
                topics = s.bot.stats.get("topic", 0)
                floors = s.bot.stats.get("floors", 0)
                total_read = s.bot.stats.get("posts_read", topics + floors)
                s.stats_topic.set(f"话题: {topics}")
                s.stats_floors.set(f"爬楼: {floors}")
                s.stats_total.set(f"已读: {total_read}")
                s.stats_like.set(
                    f"点赞: {s.bot.stats['like'] + s.bot.stats['like_reply']}"
                )
                s.stats_reply.set(f"回复: {s.bot.stats['reply']}")

        s.rt.after(0, log)

    def _start(s):
        if s._closing or s.task_registry.busy or (s.th and s.th.is_alive()):
            return False
        # 更新配置
        s.cfg["proxy"] = s.proxy_var.get()
        s.cfg["browser_backend"] = s.browser_backend_var.get()
        try:
            s.cfg["bit_api_port"] = int(s.bit_port_var.get())
        except Exception:
            s.cfg["bit_api_port"] = 54345
        if s.cfg["browser_backend"] == "bitbrowser":
            selected_id = s.bit_task_table.selected_id
            if not selected_id:
                messagebox.showerror("错误", "请先获取并选择比特浏览器窗口")
                return
            s.bit_id_var.set(selected_id)
        s.cfg["bit_window_id"] = s.bit_id_var.get().strip()
        try:
            s.cfg["simprint_api_port"] = int(s.simprint_port_var.get())
        except Exception:
            s.cfg["simprint_api_port"] = 8080
        s.cfg["simprint_api_key"] = s.simprint_key_var.get().strip()
        s.cfg["simprint_env_uuid"] = s.simprint_env_var.get().strip()
        if s.cfg["browser_backend"] == "simprint":
            if not s.cfg["simprint_api_key"]:
                messagebox.showerror("错误", "请先填写 Simprint API Key")
                return
            selected_uuid = s.simprint_task_table.selected_id
            if not selected_uuid:
                messagebox.showerror("错误", "请先获取并选择 Simprint 环境")
                return
            s.simprint_env_var.set(selected_uuid)
            s.cfg["simprint_env_uuid"] = selected_uuid
        try:
            s.cfg["like_rate"] = int(s.like_var.get()) / 100
        except:
            s.cfg["like_rate"] = 0.3
        try:
            s.cfg["reply_rate"] = int(s.reply_var.get()) / 100
        except:
            s.cfg["reply_rate"] = 0.05
        try:
            parts = s.wait_var.get().split("-")
            s.cfg["wait_min"] = float(parts[0])
            s.cfg["wait_max"] = float(parts[1]) if len(parts) > 1 else float(parts[0])
        except:
            s.cfg["wait_min"], s.cfg["wait_max"] = 1, 3

        reply_min, reply_max = parse_reply_count_range(
            s.reply_count_min_var.get(), s.reply_count_max_var.get()
        )
        s.cfg["reply_count_min"] = reply_min
        s.cfg["reply_count_max"] = reply_max
        s.reply_count_min_var.set(str(reply_min))
        s.reply_count_max_var.set("" if reply_max is None else str(reply_max))
        s.cfg["unread_only"] = s.unread_only_var.get()
        try:
            list_scroll_times = int(s.list_scroll_var.get())
            if list_scroll_times < 0:
                raise ValueError("list_scroll_times cannot be negative")
        except Exception:
            list_scroll_times = 3
        s.cfg["list_scroll_times"] = list_scroll_times
        s.list_scroll_var.set(str(list_scroll_times))

        # 读取运行模式设置
        mode = s.mode_var.get()
        target_value = 0

        if mode == "topics":
            try:
                target_value = int(s.topics_var.get())
            except:
                target_value = 50
        elif mode == "time":
            try:
                target_value = int(s.time_var.get())
            except:
                target_value = 30
        if mode in ("topics", "time") and target_value <= 0:
            messagebox.showerror("错误", "运行目标必须大于 0")
            return False
        if not any(cat.get("e", True) for cat in s.cats):
            messagebox.showerror("错误", "请至少选择一个板块")
            return False

        # 读取开关状态
        enable_like = s.enable_like_var.get()
        enable_reply = s.enable_reply_var.get()
        enable_wait = s.enable_wait_var.get()
        browse_mode = s.browse_mode_var.get()

        s.bot = Bot(
            deepcopy(s.cfg),
            deepcopy(s.cats),
            s._lg,
            s._update_info,
            s._update_progress,
            s._update_countdown,
            mode=mode,
            target_value=target_value,
            enable_like=enable_like,
            enable_reply=enable_reply,
            enable_wait=enable_wait,
            browse_mode=browse_mode,
            screen_height=s.screen_height,
        )
        backend = s.cfg["browser_backend"]
        environment_id = (
            s.cfg["bit_window_id"] if backend == "bitbrowser" else
            s.cfg["simprint_env_uuid"] if backend == "simprint" else "default"
        )
        key = task_key(backend, environment_id)
        if not s.task_registry.begin(key):
            return False
        s.initial_requirements = []
        s.status.set("运行中...")
        s._update_tray_status("运行中")
        s._refresh_task_tables()
        s._save_settings()
        s.th = None
        try:
            s.th = threading.Thread(target=s._run, args=(s.bot, key), daemon=True)
            s.th.start()
        except Exception as error:
            s._lg(f"启动任务失败: {error}")
            s._done(s.bot, key, ERROR)
            return False
        return True

    def _run(s, bot, key):
        outcome = ERROR
        try:
            outcome = bot.run_session()
        except Exception as e:
            # 后台异常不能直接更新 Tk 控件，交给主线程统一写入日志。
            s.rt.after(0, lambda error=e: s._lg(f"运行异常: {error}"))
        finally:
            s.rt.after(0, lambda: s._done(bot, key, outcome))

    def _done(s, bot, key, outcome):
        if s.bot is not bot or s.task_registry.active_key != key:
            return
        # after(0) 可能在线程返回前执行；收尾退出前不能放行下一次开始。
        if s.th and s.th.is_alive():
            s.rt.after(25, lambda: s._done(bot, key, outcome))
            return
        s.task_registry.finish(key, outcome)
        s.th = None
        status = STATUS_LABELS[s.task_registry.get(key)["status"]]
        s.status.set(status)
        s._update_tray_status(status, bot.stats)
        s._refresh_task_tables()
        s._save_settings()
        s._lg(f"任务结束：{status}")
        if s._closing:
            s._destroy_window()

    def _stop(s):
        key = s.task_registry.active_key
        if not key or not s.task_registry.request_stop(key):
            return
        s.bot.stop()
        s.status.set("正在停止...")
        s._update_tray_status("正在停止", s.bot.stats)
        s._refresh_task_tables()
        s._save_settings()

    def run(s):
        s.rt.mainloop()


if __name__ == "__main__":
    GUI().run()
