"""Per-environment task records and the GUI's single active-task reservation."""

from copy import deepcopy
from datetime import datetime


PENDING = "pending"
RUNNING = "running"
STOPPING = "stopping"
STOPPED = "stopped"
COMPLETED = "completed"
ERROR = "error"

STATUS_LABELS = {
    PENDING: "待开始",
    RUNNING: "运行中",
    STOPPING: "正在停止",
    STOPPED: "已停止",
    COMPLETED: "已完成",
    ERROR: "异常",
}


def task_key(backend, environment_id="default"):
    return f"{backend}:{environment_id}"


def normalize_entries(entries):
    """Keep distinct environment IDs, including environments with equal names."""
    result = []
    seen = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        entry_id = str(entry["id"])
        if entry_id in seen:
            continue
        seen.add(entry_id)
        result.append({"id": entry_id, "name": str(entry.get("name") or entry_id)})
    return result


class TaskRegistry:
    """Owned by the Tk main thread; workers report outcomes back to that thread."""

    def __init__(self, records=None, clock=None):
        self._clock = clock or datetime.now
        self.records = {}
        self.active_key = None
        self.finish_requested = None
        self.restore(records)

    @property
    def busy(self):
        return self.active_key is not None

    def restore(self, records):
        if self.busy or not isinstance(records, dict):
            return
        self.records = {}
        for key, record in records.items():
            if not isinstance(key, str) or not isinstance(record, dict):
                continue
            status = record.get("status", PENDING)
            if not isinstance(status, str) or status not in STATUS_LABELS:
                status = PENDING
            if status in (RUNNING, STOPPING):
                status = STOPPED
            completed_at = record.get("completed_at", "")
            try:
                completed_at = datetime.fromisoformat(completed_at).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ) if completed_at else ""
            except (TypeError, ValueError):
                completed_at = ""
            self.records[key] = {"status": status, "completed_at": completed_at}

    def get(self, key):
        return dict(self.records.get(key, {"status": PENDING, "completed_at": ""}))

    def snapshot(self):
        return deepcopy(self.records)

    def begin(self, key):
        if self.busy:
            return False
        self.active_key = key
        self.finish_requested = None
        record = self.get(key)
        record["status"] = RUNNING
        self.records[key] = record
        return True

    def request_stop(self, key, complete=False):
        if key != self.active_key or self.get(key)["status"] != RUNNING:
            return False
        self.finish_requested = COMPLETED if complete else STOPPED
        self.records[key]["status"] = STOPPING
        return True

    def finish(self, key, outcome):
        """Release only after the owning worker has exited."""
        if key != self.active_key:
            return False
        if outcome not in (COMPLETED, STOPPED, ERROR):
            outcome = ERROR
        if outcome != ERROR and self.finish_requested:
            outcome = self.finish_requested
        self.records[key]["status"] = outcome
        if outcome == COMPLETED:
            self.records[key]["completed_at"] = self._clock().strftime("%Y-%m-%d %H:%M:%S")
        self.active_key = None
        self.finish_requested = None
        return True

    def mark_complete(self, key):
        if key == self.active_key or self.get(key)["status"] == COMPLETED:
            return False
        self.records[key] = {
            "status": COMPLETED,
            "completed_at": self._clock().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return True
