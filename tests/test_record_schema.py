"""锁死执行记录的格式：字段改名、汇总对不上、被测返回漂移，这里先红。

这不是「再测一遍被测系统」，测的是**我们自己产出的数据**——
因为 B 的 judge 和 C 的看板都只认这份文件，它一变形两边全崩。
"""

from __future__ import annotations

import copy

from tools.record_schema import (
    CONTRACT_OUTPUT_FIELDS,
    FORMAT_VERSION,
    validate_payload,
    validate_record,
)


def _output(**overrides) -> dict:
    """一个字段齐全的「被测系统返回」。"""
    base = {key: None for key in CONTRACT_OUTPUT_FIELDS}
    base.update({"ok": True, "answer": "答案", "tool_calls": [], "references": [], "citation": {}})
    base.update(overrides)
    return base


def _payload() -> dict:
    records = [
        {
            "case_id": "test_demo",
            "nodeid": "tests/test_demo.py::test_demo",
            "file": "tests/test_demo.py",
            "markers": ["smoke"],
            "outcome": "passed",
            "duration_s": 0.01,
            "detail": None,
            "trace": {"input": "主题", "output": _output()},
            "run_at": "2026-10-18T00:00:00+08:00",
        }
    ]
    return {
        "format_version": FORMAT_VERSION,
        "run_at": "2026-10-18T00:00:00+08:00",
        "sut": {
            "mode": "stub",
            "engine": "research-assistant",
            "schema_version": "1.2",
            "commit": "",
            "dirty": False,
        },
        "summary": {
            "total": 1, "passed": 1, "failed": 0, "error": 0,
            "skipped": 0, "pass_rate": 100.0, "duration_s": 0.01,
        },
        "records": records,
    }


def test_valid_payload_passes():
    assert validate_payload(_payload()) == []


def test_record_missing_field_is_caught():
    payload = _payload()
    del payload["records"][0]["outcome"]
    errors = validate_payload(payload)
    assert any("缺少字段" in e for e in errors), errors


def test_summary_mismatch_is_caught():
    payload = _payload()
    payload["summary"]["passed"] = 99
    errors = validate_payload(payload)
    assert any("summary.passed" in e for e in errors), errors


def test_agent_output_field_drift_is_caught():
    """被测系统少返回一个契约字段，必须当场报出来。"""
    record = copy.deepcopy(_payload()["records"][0])
    out = dict(record["trace"]["output"])
    out.pop("citation")
    record["trace"]["output"] = out
    errors = validate_record(record)
    assert any("citation" in e for e in errors), errors


def test_format_version_mismatch_is_caught():
    payload = _payload()
    payload["format_version"] = "999"
    errors = validate_payload(payload)
    assert any("format_version" in e for e in errors), errors


def test_real_mode_without_commit_is_caught():
    """真机结果必须带 commit，否则一个月后无法复现。"""
    payload = _payload()
    payload["sut"]["mode"] = "real"
    payload["sut"]["commit"] = ""
    errors = validate_payload(payload)
    assert any("commit" in e for e in errors), errors


def test_missing_sut_is_caught():
    payload = _payload()
    del payload["sut"]
    errors = validate_payload(payload)
    assert any("sut" in e for e in errors), errors
