# -*- coding: utf-8 -*-
"""
linux.do 论坛自动浏览脚本 v2.0
功能：自动登录、浏览帖子、滚动阅读、随机点赞

使用方法：
1. 确保Chrome浏览器已安装
2. 配置代理地址（如需要）
3. 首次运行时手动登录，后续会保持登录状态
4. 运行脚本：python linux_do_auto_browse.py

依赖：pip install DrissionPage
"""

import sys
import io
import os
import random
import time
import json
from datetime import datetime
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from DrissionPage import ChromiumPage, ChromiumOptions

# ==================== 配置区域 ====================

class Config:
    """配置类"""
    # 代理设置（如不需要代理，设为None）
    PROXY = "127.0.0.1:7897"

    # 目标URL
    BASE_URL = "https://linux.do"
    CATEGORY_URL = "https://linux.do/c/develop/develop-lv2/31"

    # 浏览设置
    MIN_TOPICS_PER_SESSION = 5      # 每次会话最少浏览帖子数
    MAX_TOPICS_PER_SESSION = 15     # 每次会话最多浏览帖子数
    LIKE_PROBABILITY = 0.3          # 点赞概率 (0-1)
    LIKE_REPLY_PROBABILITY = 0.2    # 点赞回复的概率 (0-1)

    # 时间设置（秒）
    PAGE_LOAD_WAIT = 3              # 页面加载等待时间
    SCROLL_INTERVAL = (1, 3)        # 滚动间隔范围
    READ_TIME = (5, 15)             # 阅读帖子时间范围
    BETWEEN_TOPICS = (3, 8)         # 帖子之间的等待时间范围

    # 无头模式（True=后台运行，False=显示浏览器）
    HEADLESS = False

    # 日志文件
    LOG_FILE = "linux_do_browse.log"


# ==================== 日志工具 ====================

def log(message, level="INFO"):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)

    # 写入日志文件
    try:
        with open(Config.LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except:
        pass


# ==================== 浏览器管理 ====================

class BrowserManager:
    """浏览器管理类"""

    def __init__(self):
        self.page = None

    def init_browser(self):
        """初始化浏览器"""
        log("正在初始化浏览器...")

        co = ChromiumOptions()

        # 设置代理
        if Config.PROXY:
            co.set_proxy(Config.PROXY)
            log(f"已设置代理: {Config.PROXY}")

        # 反检测设置
        co.set_argument('--disable-blink-features=AutomationControlled')

        # 无头模式
        if Config.HEADLESS:
            co.headless(True)
            log("已启用无头模式")

        # 创建浏览器实例
        self.page = ChromiumPage(co)
        log("浏览器初始化完成")

        return self.page

    def close(self):
        """关闭浏览器"""
        if self.page:
            try:
                self.page.quit()
                log("浏览器已关闭")
            except:
                pass


# ==================== 论坛操作类 ====================

class LinuxDoBot:
    """linux.do 论坛自动化操作类"""

    def __init__(self, page):
        self.page = page
        self.visited_topics = set()  # 已访问的帖子
        self.liked_posts = set()     # 已点赞的帖子
        self.stats = {
            "topics_viewed": 0,
            "posts_liked": 0,
            "scroll_count": 0,
            "errors": 0
        }

    def check_login_status(self):
        """检查登录状态"""
        log("检查登录状态...")

        # 访问首页
        self.page.get(Config.BASE_URL)
        time.sleep(Config.PAGE_LOAD_WAIT)

        # 检测登录元素
        current_user = self.page.ele('#current-user', timeout=3)
        if current_user:
            # 尝试获取用户名
            try:
                username_img = self.page.ele('.current-user img', timeout=2)
                username = username_img.attr('title') if username_img else "未知用户"
            except:
                username = "已登录用户"

            log(f"登录状态: 已登录 ({username})")
            return True
        else:
            log("登录状态: 未登录", "WARNING")
            return False

    def manual_login(self):
        """引导用户手动登录"""
        log("请在浏览器中手动登录...")
        log("登录完成后，按回车键继续...")

        # 访问登录页面
        self.page.get(Config.BASE_URL)
        time.sleep(2)

        # 点击登录按钮
        login_btn = self.page.ele('.login-button', timeout=3)
        if login_btn:
            login_btn.click()
            log("已点击登录按钮，请在浏览器中完成登录")

        # 等待用户输入
        input("按回车键继续...")

        # 再次检查登录状态
        return self.check_login_status()

    def get_topic_list(self):
        """获取帖子列表"""
        log(f"正在获取帖子列表: {Config.CATEGORY_URL}")

        self.page.get(Config.CATEGORY_URL)
        time.sleep(Config.PAGE_LOAD_WAIT)

        # 获取帖子链接
        topics = []

        # 使用JS获取帖子信息
        topic_data = self.page.run_js("""
        function getTopics() {
            const links = document.querySelectorAll('.topic-list a.title');
            const topics = [];
            links.forEach(a => {
                const href = a.href;
                const title = a.textContent.trim();
                // 过滤掉分类链接，只保留帖子链接
                if (href && href.includes('/t/topic/') && title) {
                    topics.push({
                        url: href,
                        title: title.substring(0, 50)
                    });
                }
            });
            return topics;
        }
        return getTopics();
        """)

        if topic_data:
            topics = topic_data
            log(f"找到 {len(topics)} 个帖子")

        return topics

    def scroll_page(self, duration=None):
        """模拟滚动页面阅读"""
        if duration is None:
            duration = random.uniform(*Config.READ_TIME)

        log(f"开始滚动阅读，预计 {duration:.1f} 秒")

        start_time = time.time()
        scroll_count = 0

        while time.time() - start_time < duration:
            # 随机滚动距离
            scroll_distance = random.randint(200, 500)

            # 执行滚动
            self.page.run_js(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1

            # 随机等待
            time.sleep(random.uniform(*Config.SCROLL_INTERVAL))

            # 检查是否到底部
            at_bottom = self.page.run_js("""
            return (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 100;
            """)

            if at_bottom:
                log("已滚动到页面底部")
                break

        self.stats["scroll_count"] += scroll_count
        log(f"滚动完成，共滚动 {scroll_count} 次")

    def find_like_buttons(self):
        """查找所有点赞按钮"""
        # 使用JS查找点赞按钮，更可靠
        buttons_info = self.page.run_js("""
        function findLikeButtons() {
            // 多种选择器尝试
            const selectors = [
                'button.btn-toggle-reaction-like',
                '.discourse-reactions-reaction-button button',
                'button[title="点赞此帖子"]',
                '.post-menu-area button.reaction-button'
            ];

            let buttons = [];
            for (const sel of selectors) {
                const found = document.querySelectorAll(sel);
                if (found.length > 0) {
                    found.forEach((btn, idx) => {
                        // 检查是否已点赞
                        const hasLiked = btn.classList.contains('has-like') ||
                                        btn.classList.contains('my-likes') ||
                                        btn.closest('.discourse-reactions-reaction-button')?.classList.contains('has-used');

                        buttons.push({
                            index: idx,
                            selector: sel,
                            hasLiked: hasLiked,
                            title: btn.title || '',
                            visible: btn.offsetParent !== null
                        });
                    });
                    break;  // 找到就停止
                }
            }
            return buttons;
        }
        return findLikeButtons();
        """)

        return buttons_info or []

    def like_post(self, button_index=0):
        """点赞帖子"""
        try:
            # 先获取按钮信息
            buttons_info = self.find_like_buttons()

            if not buttons_info:
                log("未找到点赞按钮", "DEBUG")
                return False

            if button_index >= len(buttons_info):
                log(f"按钮索引 {button_index} 超出范围", "DEBUG")
                return False

            btn_info = buttons_info[button_index]

            # 检查是否已点赞
            if btn_info.get('hasLiked'):
                log(f"帖子 #{button_index + 1} 已点赞，跳过")
                return False

            # 使用JS点击按钮
            clicked = self.page.run_js(f"""
            function clickLikeButton(index) {{
                const selectors = [
                    'button.btn-toggle-reaction-like',
                    '.discourse-reactions-reaction-button button',
                    'button[title="点赞此帖子"]',
                    '.post-menu-area button.reaction-button'
                ];

                for (const sel of selectors) {{
                    const buttons = document.querySelectorAll(sel);
                    if (buttons.length > index) {{
                        const btn = buttons[index];
                        // 滚动到按钮位置
                        btn.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                        // 等待一下再点击
                        setTimeout(() => btn.click(), 300);
                        return true;
                    }}
                }}
                return false;
            }}
            return clickLikeButton({button_index});
            """)

            if clicked:
                time.sleep(1)  # 等待点赞动画
                self.stats["posts_liked"] += 1
                log(f"成功点赞帖子 #{button_index + 1}")
                return True
            else:
                log(f"点击点赞按钮失败", "DEBUG")
                return False

        except Exception as e:
            log(f"点赞失败: {e}", "ERROR")
            self.stats["errors"] += 1
            return False

    def browse_topic(self, topic_url, topic_title):
        """浏览单个帖子"""
        log(f"正在浏览: {topic_title}")

        try:
            # 访问帖子
            self.page.get(topic_url)
            time.sleep(Config.PAGE_LOAD_WAIT)

            # 标记为已访问
            self.visited_topics.add(topic_url)
            self.stats["topics_viewed"] += 1

            # 滚动阅读
            self.scroll_page()

            # 等待页面稳定
            time.sleep(1)

            # 获取点赞按钮信息
            buttons_info = self.find_like_buttons()
            log(f"找到 {len(buttons_info)} 个点赞按钮")

            if buttons_info:
                # 随机决定是否点赞主帖
                if random.random() < Config.LIKE_PROBABILITY:
                    log("决定点赞主帖")
                    self.like_post(0)
                    time.sleep(random.uniform(0.5, 1.5))

                # 随机决定是否点赞回复
                if len(buttons_info) > 1:
                    for i in range(1, len(buttons_info)):
                        if random.random() < Config.LIKE_REPLY_PROBABILITY:
                            log(f"决定点赞回复 #{i}")
                            self.like_post(i)
                            time.sleep(random.uniform(0.5, 1.5))

            log(f"完成浏览: {topic_title}")
            return True

        except Exception as e:
            log(f"浏览帖子失败: {e}", "ERROR")
            self.stats["errors"] += 1
            return False

    def run_session(self):
        """运行一次浏览会话"""
        log("=" * 50)
        log("开始新的浏览会话")
        log("=" * 50)

        # 检查登录状态
        if not self.check_login_status():
            if not self.manual_login():
                log("登录失败，退出", "ERROR")
                return False

        # 获取帖子列表
        topics = self.get_topic_list()
        if not topics:
            log("未找到帖子，退出", "ERROR")
            return False

        # 过滤已访问的帖子
        new_topics = [t for t in topics if t['url'] not in self.visited_topics]
        log(f"新帖子数量: {len(new_topics)}")

        if not new_topics:
            log("没有新帖子可浏览")
            return True

        # 随机选择要浏览的帖子数量
        num_to_browse = random.randint(
            Config.MIN_TOPICS_PER_SESSION,
            min(Config.MAX_TOPICS_PER_SESSION, len(new_topics))
        )
        log(f"本次会话将浏览 {num_to_browse} 个帖子")

        # 随机打乱顺序
        random.shuffle(new_topics)

        # 浏览帖子
        for i, topic in enumerate(new_topics[:num_to_browse]):
            log(f"\n--- 帖子 {i + 1}/{num_to_browse} ---")

            self.browse_topic(topic['url'], topic['title'])

            # 帖子之间等待
            if i < num_to_browse - 1:
                wait_time = random.uniform(*Config.BETWEEN_TOPICS)
                log(f"等待 {wait_time:.1f} 秒后继续...")
                time.sleep(wait_time)

        # 输出统计
        self.print_stats()

        return True

    def print_stats(self):
        """输出统计信息"""
        log("\n" + "=" * 50)
        log("会话统计")
        log("=" * 50)
        log(f"浏览帖子数: {self.stats['topics_viewed']}")
        log(f"点赞次数: {self.stats['posts_liked']}")
        log(f"滚动次数: {self.stats['scroll_count']}")
        log(f"错误次数: {self.stats['errors']}")
        log("=" * 50)


# ==================== 主程序 ====================

def main():
    """主函数"""
    log("=" * 60)
    log("linux.do 论坛自动浏览脚本启动")
    log("=" * 60)

    browser = BrowserManager()

    try:
        # 初始化浏览器
        page = browser.init_browser()

        # 创建机器人实例
        bot = LinuxDoBot(page)

        # 运行浏览会话
        bot.run_session()

        log("\n脚本执行完成")

        # 保持浏览器打开一段时间（可选）
        if not Config.HEADLESS:
            log("浏览器将在30秒后关闭，或按Ctrl+C立即退出")
            time.sleep(30)

    except KeyboardInterrupt:
        log("\n用户中断，正在退出...")

    except Exception as e:
        log(f"发生错误: {e}", "ERROR")
        import traceback
        traceback.print_exc()

    finally:
        browser.close()


if __name__ == "__main__":
    main()
