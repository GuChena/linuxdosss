# -*- coding: utf-8 -*-
"""
爬楼模式测试脚本
用于验证爬楼模式的可行性和效果

测试流程：
1. 获取初始阅读进度
2. 随机访问板块，点击"回复"按钮按回复数排序
3. 进入高回复数帖子，使用楼层计数器跟踪进度
4. 智能滚动：等待2-4秒后滚动600-1200px，直到读完所有楼层
5. 获取最终阅读进度，对比变化

关键特性：
- 支持两种楼层显示格式：
  * 宽窗口：.timeline-replies 显示 "1/169"
  * 窄窗口：#topic-progress .nums 显示 <span>69</span><span>/</span><span>74</span>
- 使用楼层计数器作为唯一真实来源（准确可靠）
- 移除不可靠的蓝色指示器检测
- 移除错误的"到底部"检测（页面有无限滚动）
- 保持2-4秒滚动间隔，确保蓝点有时间消失
- 滚动距离600-1200px，每次显示约3-4条评论
- 随机点赞功能（30%概率）
"""

import sys
import time
import random
from DrissionPage import ChromiumPage, ChromiumOptions

# 配置
PROXY = "127.0.0.1:7897"  # 代理地址，不需要则设为 None
BASE_URL = "https://linux.do"
CONNECT_URL = "https://connect.linux.do"
HEADLESS = True  # 先用有头模式登录一次，登录后可以改为 True
TARGET_FLOORS = 20  # 目标楼层数量（测试用）
MAX_TOPICS_PER_CATEGORY = 5  # 每个板块最多爬取的主题数
LIKE_PROBABILITY = 0.3  # 点赞概率

# 板块列表
CATEGORIES = [
    {"name": "开发调优", "url": "https://linux.do/c/develop/4"},
    {"name": "资源荟萃", "url": "https://linux.do/c/resource/14"},
    {"name": "福利羊毛", "url": "https://linux.do/c/welfare/36"},
    {"name": "搞七捻三", "url": "https://linux.do/c/gossip/11"},
    {"name": "前沿快讯", "url": "https://linux.do/c/news/34"},
    {"name": "运营反馈", "url": "https://linux.do/c/feedback/2"},
]

def log(msg):
    """打印日志"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def init_browser():
    """初始化浏览器"""
    log("初始化浏览器...")
    co = ChromiumOptions()
    
    # 设置用户数据目录，确保有头和无头模式共享登录状态
    import os
    user_data_dir = os.path.join(os.getcwd(), "browser_data")
    co.set_user_data_path(user_data_dir)
    log(f"使用用户数据目录: {user_data_dir}")
    
    if PROXY:
        co.set_proxy(PROXY)
        log(f"已设置代理: {PROXY}")
    
    co.set_argument("--disable-blink-features=AutomationControlled")
    
    if HEADLESS:
        co.headless(True)
        log("已启用无头模式")
    
    page = ChromiumPage(co)
    log("浏览器初始化完成")
    return page

def check_login(page):
    """检查登录状态"""
    log("检查登录状态...")
    page.get(BASE_URL)
    time.sleep(3)
    
    try:
        user_ele = page.ele("#current-user", timeout=3)
        if user_ele:
            log("已登录")
            return True
    except:
        pass
    
    if HEADLESS:
        log("⚠ 无头模式下未登录，请先用有头模式登录一次")
        log("提示：将 HEADLESS 设为 False，运行一次登录后，再改回 True")
        return False
    
    log("未登录，请在浏览器中登录后按回车继续...")
    input()
    return check_login(page)

def get_reading_progress(page):
    """获取阅读进度"""
    log("获取阅读进度...")
    try:
        page.get(CONNECT_URL)
        time.sleep(4)
        
        progress = page.run_js("""
        function getProgress() {
            const result = {
                username: '',
                level: '',
                topics_read: 0,
                topics_read_all_time: 0,
                reading_time: 0
            };
            
            // 获取用户名和等级
            const h1 = document.querySelector('h1');
            if (h1) {
                const text = h1.textContent;
                const match = text.match(/\\((.+?)\\)\\s*(\\d+)级用户/);
                if (match) {
                    result.username = match[1];
                    result.level = match[2];
                }
            }
            
            // 获取阅读进度 - 使用更精确的选择器
            const allText = document.body.innerText;
            
            // 方法1：尝试匹配 "已读帖子 X / Y" 或 "已读帖子\nX / Y"
            let topicsMatch = allText.match(/已读帖子[\\s\\n]+(\\d+)[\\s\\n]*\\/[\\s\\n]*(\\d+)/);
            if (topicsMatch) {
                result.topics_read = parseInt(topicsMatch[1]);
            } else {
                // 方法2：尝试只匹配数字（如果格式不同）
                const lines = allText.split('\\n');
                for (let i = 0; i < lines.length; i++) {
                    if (lines[i].includes('已读帖子') && !lines[i].includes('所有时间')) {
                        // 查找下一行的数字
                        if (i + 1 < lines.length) {
                            const nextLine = lines[i + 1];
                            const numMatch = nextLine.match(/(\\d+)[\\s\\/]+(\\d+)/);
                            if (numMatch) {
                                result.topics_read = parseInt(numMatch[1]);
                                break;
                            }
                        }
                    }
                }
            }
            
            // 匹配 "已读帖子（所有时间） X"
            const topicsAllTimeMatch = allText.match(/已读帖子[（(]所有时间[）)][\\s\\n]+(\\d+)/);
            if (topicsAllTimeMatch) {
                result.topics_read_all_time = parseInt(topicsAllTimeMatch[1]);
            }
            
            // 匹配 "阅读时长 X 分钟"
            const timeMatch = allText.match(/阅读时长[\\s\\n]+(\\d+)[\\s\\n]*分钟/);
            if (timeMatch) {
                result.reading_time = parseInt(timeMatch[1]);
            }
            
            return result;
        }
        return getProgress();
        """)
        
        if progress:
            log(f"用户: {progress.get('username', '未知')}")
            log(f"等级: {progress.get('level', '未知')}级")
            log(f"已读帖子: {progress.get('topics_read', 0)}")
            log(f"已读帖子（所有时间）: {progress.get('topics_read_all_time', 0)}")
            log(f"阅读时长: {progress.get('reading_time', 0)} 分钟")
            return progress
    except Exception as e:
        log(f"获取进度失败: {e}")
    
    return None

def get_category_topics(page, category_url, category_name):
    """获取板块的帖子（按回复数排序）"""
    log(f"访问板块: {category_name}")
    page.get(category_url)
    time.sleep(3)
    
    # 点击"回复"按钮进行排序
    log("点击'回复'按钮进行排序...")
    clicked = page.run_js("""
    function clickRepliesSort() {
        // 查找回复排序按钮
        const replyButton = document.querySelector('th[data-sort-order="posts"] button');
        if (replyButton) {
            replyButton.click();
            return true;
        }
        return false;
    }
    return clickRepliesSort();
    """)
    
    if clicked:
        log("已点击回复排序按钮")
        time.sleep(2)  # 等待排序完成
    else:
        log("未找到回复排序按钮，使用默认排序")
    
    # 获取帖子列表
    topics = page.run_js("""
    function getTopics() {
        const links = document.querySelectorAll('.topic-list a.title');
        const topics = [];
        links.forEach(a => {
            const href = a.href;
            const title = a.textContent.trim();
            if (href && href.includes('/t/') && title) {
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
    
    if topics:
        log(f"找到 {len(topics)} 个帖子")
        return topics[:MAX_TOPICS_PER_CATEGORY]
    
    return []

def get_floor_info(page):
    """获取楼层信息（当前楼层/总楼层）
    
    支持两种显示格式：
    1. 宽窗口：.timeline-replies 显示 "1/169"
    2. 窄窗口：#topic-progress .nums 显示 <span>69</span><span>/</span><span>74</span>
    """
    floor_info = page.run_js("""
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

def do_like(page, button_index=0):
    """点赞帖子或回复"""
    try:
        result = page.run_js(f"""
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
        return clickLike({button_index});
        """)
        
        if result:
            time.sleep(random.uniform(0.5, 1))
            if button_index == 0:
                log(f"点赞主帖成功")
            else:
                log(f"点赞回复 #{button_index} 成功")
            return True
    except Exception as e:
        log(f"点赞失败: {e}")
    return False

def climb_topic(page, topic_url, topic_title):
    """爬楼单个帖子"""
    log(f"开始爬楼: {topic_title}")
    
    try:
        # 访问帖子
        page.get(topic_url)
        time.sleep(3)
        
        # 获取初始楼层信息
        floor_info = get_floor_info(page)
        if not floor_info:
            log("⚠ 无法获取楼层信息（未找到 .timeline-replies 或 #topic-progress），跳过此帖")
            return 0
        
        total_floors = floor_info['total']
        log(f"帖子总楼层数: {total_floors} (来源: {floor_info.get('source', 'unknown')})")
        
        if total_floors < 10:
            log(f"楼层数太少（{total_floors}），跳过此帖")
            return 0
        
        scroll_count = 0
        likes_count = 0
        floors_read = 1  # 从第1楼开始（主帖）
        last_floor = 1
        stuck_count = 0  # 楼层卡住计数
        
        # 获取点赞按钮总数
        total_like_buttons = page.run_js("""
        return document.querySelectorAll('button.btn-toggle-reaction-like').length;
        """) or 0
        
        log(f"找到 {total_like_buttons} 个点赞按钮")
        
        # 随机点赞主帖
        if total_like_buttons > 0 and random.random() < LIKE_PROBABILITY:
            if do_like(page, 0):
                likes_count += 1
                time.sleep(random.uniform(0.5, 1))
        
        # 开始爬楼
        while floors_read < total_floors:
            # 等待阅读
            wait_time = random.uniform(2, 4)
            log(f"等待 {wait_time:.1f} 秒...")
            time.sleep(wait_time)
            
            # 滚动页面
            scroll_distance = random.randint(600, 1200)
            page.run_js(f"window.scrollBy(0, {scroll_distance})")
            scroll_count += 1
            
            # 等待页面更新
            time.sleep(0.5)
            
            # 获取当前楼层
            floor_info = get_floor_info(page)
            if floor_info:
                current_floor = floor_info['current']
                floors_read = current_floor
                source = floor_info.get('source', 'unknown')
                
                if current_floor > last_floor:
                    log(f"滚动 #{scroll_count}，距离 {scroll_distance}px → 当前楼层: {current_floor}/{total_floors} [{source}]")
                    last_floor = current_floor
                    stuck_count = 0
                else:
                    log(f"滚动 #{scroll_count}，距离 {scroll_distance}px → 楼层未变化: {current_floor}/{total_floors} [{source}]")
                    stuck_count += 1
                    
                    # 如果楼层长时间不变，可能需要更大的滚动
                    if stuck_count >= 3:
                        log("楼层卡住，尝试更大的滚动距离")
                        page.run_js(f"window.scrollBy(0, 1500)")
                        time.sleep(1)
                        stuck_count = 0
            else:
                log(f"滚动 #{scroll_count}，距离 {scroll_distance}px → ⚠ 无法获取楼层信息（未找到 .timeline-replies 或 #topic-progress）")
            
            # 随机点赞回复（每10次滚动尝试一次）
            if scroll_count % 10 == 0 and total_like_buttons > 1:
                if random.random() < LIKE_PROBABILITY:
                    # 随机选择一个回复点赞
                    reply_index = random.randint(1, min(total_like_buttons - 1, 10))
                    if do_like(page, reply_index):
                        likes_count += 1
                        time.sleep(random.uniform(0.5, 1))
            
            # 安全检查：避免无限循环
            if scroll_count >= 200:
                log("达到最大滚动次数，停止爬楼")
                break
        
        log(f"爬楼完成: 滚动 {scroll_count} 次，读取 {floors_read}/{total_floors} 楼，点赞 {likes_count} 次")
        return floors_read, likes_count
        
    except Exception as e:
        log(f"爬楼失败: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0

def main():
    """主函数"""
    log("=" * 60)
    log("爬楼模式测试脚本")
    log(f"目标: 读取 {TARGET_FLOORS} 个楼层")
    log("=" * 60)
    
    # 初始化浏览器
    page = init_browser()
    
    try:
        # 检查登录
        if not check_login(page):
            log("登录失败，退出")
            return
        
        # 获取初始进度
        log("\n" + "=" * 60)
        log("步骤 1: 获取初始阅读进度")
        log("=" * 60)
        progress_before = get_reading_progress(page)
        
        if not progress_before:
            log("无法获取初始进度，继续测试...")
            progress_before = {"topics_read": 0, "topics_read_all_time": 0, "reading_time": 0}
        
        # 随机打乱板块顺序
        import random as rand
        categories = CATEGORIES.copy()
        rand.shuffle(categories)
        
        total_floors = 0
        topics_climbed = 0
        total_likes = 0  # 总点赞数
        start_time = time.time()  # 记录开始时间
        
        # 遍历板块，直到达到目标楼层数量
        for category in categories:
            if total_floors >= TARGET_FLOORS:
                log(f"\n已达到目标楼层数量 {TARGET_FLOORS}，停止爬楼")
                break
            
            log("\n" + "=" * 60)
            log(f"步骤 2.{categories.index(category) + 1}: 处理板块 - {category['name']}")
            log("=" * 60)
            
            # 获取板块帖子
            topics = get_category_topics(page, category['url'], category['name'])
            
            if not topics:
                log(f"板块 {category['name']} 未找到帖子，跳过")
                continue
            
            # 爬楼该板块的帖子
            for i, topic in enumerate(topics):
                if total_floors >= TARGET_FLOORS:
                    break
                
                log(f"\n--- 帖子 {i + 1}/{len(topics)} ---")
                floors_count, likes_count = climb_topic(page, topic['url'], topic['title'])
                total_floors += floors_count
                total_likes += likes_count
                topics_climbed += 1
                
                log(f"当前累计: 主题 {topics_climbed} 个，楼层 {total_floors}/{TARGET_FLOORS}，点赞 {total_likes} 次")
                
                # 帖子之间等待
                if i < len(topics) - 1 and total_floors < TARGET_FLOORS:
                    wait_time = random.uniform(2, 4)
                    log(f"等待 {wait_time:.1f} 秒后继续...")
                    time.sleep(wait_time)
        
        # 获取最终进度
        log("\n" + "=" * 60)
        log("步骤 3: 获取最终阅读进度")
        log("=" * 60)
        progress_after = get_reading_progress(page)
        
        if not progress_after:
            log("无法获取最终进度")
            progress_after = {"topics_read": 0, "topics_read_all_time": 0, "reading_time": 0}
        
        # 计算耗时
        elapsed_time = time.time() - start_time
        elapsed_minutes = int(elapsed_time / 60)
        elapsed_seconds = int(elapsed_time % 60)
        
        # 对比进度
        log("\n" + "=" * 60)
        log("步骤 4: 测试结果统计")
        log("=" * 60)
        
        topics_diff = progress_after.get('topics_read', 0) - progress_before.get('topics_read', 0)
        topics_all_time_diff = progress_after.get('topics_read_all_time', 0) - progress_before.get('topics_read_all_time', 0)
        time_diff = progress_after.get('reading_time', 0) - progress_before.get('reading_time', 0)
        
        log(f"爬楼统计:")
        log(f"  - 爬取主题数: {topics_climbed}")
        log(f"  - 读取楼层数: {total_floors}")
        log(f"  - 点赞次数: {total_likes}")
        log(f"  - 耗时: {elapsed_minutes} 分 {elapsed_seconds} 秒")
        log("")
        log(f"进度变化:")
        log(f"  - 已读帖子: {progress_before.get('topics_read', 0)} -> {progress_after.get('topics_read', 0)} (增加 {topics_diff})")
        log(f"  - 已读帖子（所有时间）: {progress_before.get('topics_read_all_time', 0)} -> {progress_after.get('topics_read_all_time', 0)} (增加 {topics_all_time_diff})")
        log(f"  - 阅读时长: {progress_before.get('reading_time', 0)} -> {progress_after.get('reading_time', 0)} (增加 {time_diff} 分钟)")
        
        log("\n" + "=" * 60)
        if topics_diff > 0 or topics_all_time_diff > 0 or time_diff > 0:
            log("✓ 爬楼模式有效！进度有增长")
            log(f"  效率分析:")
            if total_floors > 0:
                efficiency = topics_all_time_diff / total_floors
                log(f"    - 每个楼层约等于 {efficiency:.3f} 个帖子")
            if elapsed_time > 0:
                floors_per_minute = total_floors / (elapsed_time / 60)
                log(f"    - 爬楼速度: {floors_per_minute:.1f} 楼/分钟")
            if total_likes > 0:
                log(f"    - 点赞效率: {total_likes} 次点赞")
        else:
            log("✗ 爬楼模式可能无效，进度无变化")
        log("=" * 60)
        
        if HEADLESS:
            log("\n✓ 无头模式测试成功！")
        
        log("\n测试完成，浏览器将在 10 秒后关闭")
        time.sleep(10)
        
    except KeyboardInterrupt:
        log("\n用户中断")
    except Exception as e:
        log(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            page.quit()
        except:
            pass

if __name__ == "__main__":
    main()
