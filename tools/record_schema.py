"""执行记录（reports/latest/results.json）的格式契约。

这份文件只服务两个消费方：
- B 的 judge：读 `records[].trace.output`（被测系统的完整返回）
- C 的看板：读 `summary` 与 `records[].outcome`

所以它的字段一旦定下来就**只增不减**，改名等于两边一起返工。
本模块是唯一的口径来源：生产端（conftest）写完校验，CI 再校验一次。
"""

from __future__ import annotations

FORMAT_VERSION = "1"

TOP_KEYS = ("format_version", "run_at", "sut", "summary", "records")
SUT_KEYS = ("mode", "engine", "schema_version", "commit", "dirty")
SUT_MODES = ("stub", "real")
SUMMARY_KEYS = ("total", "passed", "failed", "error", "skipped", "pass_rate", "duration_s")
RECORD_KEYS = (
    "case_id", "nodeid", "file", "markers",
    "outcome", "duration_s", "detail", "trace", "run_at",
)
OUTCOMES = ("passed", "failed", "error", "skipped")

# 被测系统的 16 个顶层字段（接口契约 v1.2）
CONTRACT_OUTPUT_FIELDS = (
    "schema_version", "engine", "run_id", "ok", "prompt", "answer",
    "tool_calls", "tools", "references", "citation", "self_eval",
    "stages", "retrieval_notes", "usage", "warnings", "error",
)


def validate_record(record: dict, where: str = "") -> list[str]:
    """校验单条记录，返回错误列表（空列表 = 通过）。"""
    errors: list[str] = []
    tag = f"{where or record.get('case_id', '?')}"

    missing = [k for k in RECORD_KEYS if k not in record]
    if missing:
        errors.append(f"[{tag}] 缺少字段：{missing}")

    if record.get("outcome") not in OUTCOMES:
        errors.append(f"[{tag}] outcome 非法：{record.get('outcome')!r}（应为 {OUTCOMES}）")

    if not isinstance(record.get("duration_s"), (int, float)):
        errors.append(f"[{tag}] duration_s 必须是数字")

    if not isinstance(record.get("trace"), dict):
        errors.append(f"[{tag}] trace 必须是对象")
        return errors

    output = record["trace"].get("output")
    if output is not None:
        if not isinstance(output, dict):
            errors.append(f"[{tag}] trace.output 必须是对象（被测系统的返回）")
        else:
            missing_out = [k for k in CONTRACT_OUTPUT_FIELDS if k not in output]
            if missing_out:
                errors.append(
                    f"[{tag}] trace.output 缺少契约字段：{missing_out}"
                    "（被测系统的返回结构变了，先对齐再改这里）"
                )
    return errors


def validate_payload(payload: dict) -> list[str]:
    """校验整份执行记录。"""
    errors: list[str] = []

    missing = [k for k in TOP_KEYS if k not in payload]
    if missing:
        return [f"顶层缺少字段：{missing}"]

    if payload["format_version"] != FORMAT_VERSION:
        errors.append(
            f"format_version 不符：文件是 {payload['format_version']}，"
            f"当前契约是 {FORMAT_VERSION}"
        )

    summary = payload.get("summary") or {}
    missing_sum = [k for k in SUMMARY_KEYS if k not in summary]
    if missing_sum:
        errors.append(f"summary 缺少字段：{missing_sum}")

    sut = payload.get("sut")
    if not isinstance(sut, dict):
        errors.append("sut 必须是对象（记录本次测的是哪个版本）")
    else:
        missing_sut = [k for k in SUT_KEYS if k not in sut]
        if missing_sut:
            errors.append(f"sut 缺少字段：{missing_sut}")
        if sut.get("mode") not in SUT_MODES:
            errors.append(f"sut.mode 非法：{sut.get('mode')!r}（应为 {SUT_MODES}）")
        if not isinstance(sut.get("dirty"), bool):
            errors.append("sut.dirty 必须是布尔值")
        if sut.get("mode") == "real" and not sut.get("commit"):
            errors.append(
                "sut.mode=real 但 sut.commit 为空——真机结果无法复现，"
                "检查 AGENT_SRC 是否指向一个 git 仓库"
            )

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records 必须是非空数组")
        return errors

    for record in records:
        errors.extend(validate_record(record))

    # 汇总数字必须和明细对得上——看板只读 summary，对不上就是谎报
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for record in records:
        counts[record.get("outcome", "error")] = counts.get(record.get("outcome", "error"), 0) + 1
    if summary.get("total") != len(records):
        errors.append(f"summary.total={summary.get('total')} 与明细 {len(records)} 条不符")
    for key, value in counts.items():
        if summary.get(key) != value:
            errors.append(f"summary.{key}={summary.get(key)} 与明细统计 {value} 不符")

    return errors
