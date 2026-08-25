"""Per-session counters and progress mapping helpers."""

import re


def new_stats():
    """Return a fresh set of counters for one run."""
    return {
        "topic": 0,
        "posts_read": 0,
        "like": 0,
        "reply": 0,
        "like_reply": 0,
        "floors": 0,
    }


def add_read_progress(stats, amount):
    """Add observed floor progress to the floor and post counters."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return 0

    amount = max(0, amount)
    stats["floors"] = stats.get("floors", 0) + amount
    stats["posts_read"] = stats.get("posts_read", 0) + amount
    return amount


def add_topic_progress(stats):
    """Record one successfully opened topic."""
    stats["topic"] = stats.get("topic", 0) + 1
    stats["posts_read"] = stats.get("posts_read", 0) + 1


def _normalize_metric_name(name):
    return re.sub(r"[\s:：()（）]", "", str(name or "")).lower()


def progress_added_for_metric(name, stats):
    """Return the local estimate for one progress metric, or ``None``."""
    metric = _normalize_metric_name(name)

    if any(marker in metric for marker in ("浏览话题", "阅读话题", "readtopics")):
        return stats.get("topic", 0)

    if any(
        marker in metric
        for marker in ("浏览帖子", "阅读帖子", "阅读楼层", "readposts")
    ):
        return stats.get(
            "posts_read", stats.get("topic", 0) + stats.get("floors", 0)
        )

    if any(marker in metric for marker in ("收到的赞", "收到赞", "likesreceived")):
        return None

    if any(
        marker in metric
        for marker in ("给出赞", "给出的赞", "发出赞", "点赞", "likesgiven")
    ):
        return stats.get("like", 0) + stats.get("like_reply", 0)

    if any(marker in metric for marker in ("回复帖子", "回复", "发帖", "replies")):
        return stats.get("reply", 0)

    return None
