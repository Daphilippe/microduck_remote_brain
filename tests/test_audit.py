from __future__ import annotations

import json

from microduck_remote_brain.audit import JsonlAuditLog
from microduck_remote_brain.executor import LifecycleEvent


def test_jsonl_audit_records_lifecycle_and_decisions(tmp_path) -> None:
    path = tmp_path / "audit" / "events.jsonl"
    audit = JsonlAuditLog(path)

    audit.write("perception.completed", observation="clear floor")
    audit.lifecycle(
        LifecycleEvent(
            event="plan.completed",
            plan_id="plan-1",
            step_id=None,
            monotonic_time=1.5,
        )
    )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "perception.completed",
        "plan.completed",
    ]
    assert records[1]["plan_id"] == "plan-1"