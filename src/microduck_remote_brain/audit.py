from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .executor import LifecycleEvent


class JsonlAuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def lifecycle(self, event: LifecycleEvent) -> None:
        facts = asdict(event)
        event_name = str(facts.pop("event"))
        self.write(event_name, category="lifecycle", **facts)

    def write(self, event: str, **facts: Any) -> None:
        record = {"event": event, "wall_time": time.time(), **facts}
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        with self._lock, self._path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")