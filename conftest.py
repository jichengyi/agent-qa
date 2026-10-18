"""公共 fixture 与执行记录落盘。

两条职责，别混在一起：
1. 给用例提供被测对象（agent）和记录通道（trace）；
2. 把每条用例的执行结果写成结构化 JSON，供 B 的 judge 打分、C 的看板读取。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.record_schema import FORMAT_VERSION, validate_payload  # noqa: E402

REPORT_DIR = ROOT / "reports" / "latest"
HISTORY_FILE = ROOT / "reports" / "history.jsonl"

KNOWN_MARKERS = ("smoke", "contract", "safety", "adversarial", "slow")

_STATE: dict[str, dict] = {}
_RECORDS: list[dict] = []
_NOW = ""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-record",
        action="store_true",
        default=False,
        help="只跑用例，不落盘 reports/latest/results.json",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    global _NOW
    _NOW = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# 批量评测一律关缓存：缓存键不含故障注入状态，开着会让两条用例互相串结果
# （C 的答疑第 3 节有实测：B 案例本该 ok=False，却命中了 A 的成功缓存）
DEFAULT_RUN_OPTIONS = {"use_cache": False}


class _Agent:
    """统一注入评测默认参数，避免 18 条用例每条都手写 use_cache=False。"""

    def __init__(self, client) -> None:
        self._client = client
        self.name = getattr(client, "name", "unknown")
        self.version = getattr(client, "version", "")

    def run(self, prompt: str, **options: object) -> dict:
        merged = {**DEFAULT_RUN_OPTIONS, **options}
        return self._client.run(prompt, **merged)


def _build_agent() -> _Agent:
    """被测对象的唯一入口。

    AGENT_IMPL=real 时走真实实现（real_adapter），否则用本地替身。
    接真机只需要设环境变量，用例一行都不用改。
    """
    if os.environ.get("AGENT_IMPL", "").strip().lower() == "real":
        from agent_under_test.real_adapter import RealAgent

        return _Agent(RealAgent())
    from agent_under_test import StubAgent

    return _Agent(StubAgent())


@pytest.fixture(scope="session")
def agent() -> _Agent:
    """被测智能体。run(prompt, **options) -> dict，字段契约见 docs/接口契约速查.md。"""
    client = _build_agent()
    print(f"\n[被测对象] {client.name} v{client.version}")
    return client


class Trace:
    """用例侧写执行记录的通道：trace.record(input=..., output=...)"""

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.data: dict = {}

    def record(self, **kwargs) -> None:
        self.data.update(kwargs)


@pytest.fixture
def trace(request: pytest.FixtureRequest) -> Trace:
    t = Trace(request.node.nodeid)
    _STATE.setdefault(request.node.nodeid, {})["trace"] = t
    yield t


def pytest_runtest_setup(item: pytest.Item) -> None:
    state = _STATE.setdefault(item.nodeid, {})
    state["markers"] = sorted(
        marker.name for marker in item.iter_markers() if marker.name in KNOWN_MARKERS
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    nodeid = report.nodeid
    state = _STATE.setdefault(nodeid, {})

    if report.when == "call":
        state["outcome"] = report.outcome
        state["duration"] = round(report.duration, 3)
        state["detail"] = None if report.passed else str(report.longrepr)
    elif report.when == "setup" and report.failed:
        state["outcome"] = "error"
        state["duration"] = round(report.duration, 3)
        state["detail"] = str(report.longrepr)
    elif report.when == "teardown":
        if "outcome" not in state:
            _STATE.pop(nodeid, None)
            return
        trace_obj = state.pop("trace", None)
        _RECORDS.append(
            {
                "case_id": _humanize(nodeid.split("::")[-1]),
                "nodeid": _humanize(nodeid),
                "file": nodeid.split("::")[0],
                "markers": state.get("markers", []),
                "outcome": state["outcome"],
                "duration_s": state["duration"],
                "detail": state["detail"],
                "trace": trace_obj.data if trace_obj else {},
                "run_at": _NOW,
            }
        )
        _STATE.pop(nodeid, None)


def _humanize(text: str) -> str:
    """pytest 会把非 ASCII 的 nodeid 转成 \\uXXXX 转义，这里还原成可读中文。"""
    if "\\u" not in text and "\\x" not in text:
        return text
    try:
        return text.encode("latin-1", "backslashreplace").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _summarize(records: list[dict]) -> dict:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for r in records:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    total = len(records)
    return {
        "total": total,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "error": counts["error"],
        "skipped": counts["skipped"],
        "pass_rate": round(counts["passed"] / total * 100, 1) if total else 0.0,
        "duration_s": round(sum(r["duration_s"] for r in records), 2),
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if session.config.getoption("--no-record", default=False):
        return
    if not _RECORDS:
        return

    summary = _summarize(_RECORDS)
    payload = {
        "format_version": FORMAT_VERSION,
        "run_at": _NOW,
        "summary": summary,
        "records": _RECORDS,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 生产端自检：格式一旦漂移，当场喊出来，别等 C 的看板崩了才发现
    problems = validate_payload(payload)
    if problems:
        print("\n[执行记录] 格式校验未通过（契约 v%s）：" % FORMAT_VERSION)
        for item in problems:
            print(f"  - {item}")
        print("  → 字段只增不减，改名先改 tools/record_schema.py 并通知 B / C\n")
    else:
        print(f"\n[执行记录] {REPORT_DIR / 'results.json'}（格式校验通过）")

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_at": _NOW, **summary}, ensure_ascii=False) + "\n")
