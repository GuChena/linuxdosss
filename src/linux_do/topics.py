# -*- coding: utf-8 -*-
"""Topic selection helpers for Linux.do list pages."""


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
