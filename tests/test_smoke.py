"""冒烟用例：主干链路能不能走通。

统一按《自动化评测接口说明》v1.1 的契约写：run(prompt) -> 16 字段 dict，
用 ok 判断成败，字段名一律用契约原名（tool_calls[].name / references / citation）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke

CONTRACT_FIELDS = {
    "schema_version", "engine", "run_id", "ok", "prompt", "answer",
    "tool_calls", "tools", "references", "citation", "self_eval",
    "stages", "retrieval_notes", "usage", "warnings", "error",
}

TOPIC = "检索增强生成中的引用幻觉检测方法"


def test_returns_all_contract_fields(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    missing = CONTRACT_FIELDS - set(resp)
    assert not missing, f"返回缺少契约字段：{sorted(missing)}"
    assert resp["ok"] is True, f"正常主题应 ok=True，实际 {resp.get('error')}"
    assert resp["schema_version"] == "1.2", "契约已升到 1.2（v1.2 新增 usage.context、references 按文档聚合）"
    assert resp["engine"] == "research-assistant"


def test_answer_is_non_empty(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    assert resp["ok"] is True
    assert resp["answer"].strip(), "ok=True 但 answer 为空"
    assert len(resp["answer"]) >= 50, f"报告过短：{len(resp['answer'])} 字"


def test_tool_calls_sequence(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    calls = resp["tool_calls"]
    assert calls, "没有任何工具调用记录"
    assert [c["seq"] for c in calls] == list(range(1, len(calls) + 1)), "seq 必须从 1 连续递增"
    assert [c["name"] for c in calls] == [
        "search_papers_web",
        "retrieve_local_library",
        "search_local_knowledge",
    ], "工具调用顺序与真实执行顺序不符"
    for call in calls:
        assert call["status"] in ("ok", "error"), f"未知状态：{call['status']}"
        assert isinstance(call["duration_ms"], (int, float))


def test_tools_dedup_and_order(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    assert resp["tools"] == [c["name"] for c in resp["tool_calls"]], "tools 与 tool_calls 不一致"
    assert len(resp["tools"]) == len(set(resp["tools"])), "tools 必须去重"


def test_usage_and_stages(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    usage = resp["usage"]
    # 真机口径（2026-10-19 实测 10 键）：工具数叫 tool_calls、来源数叫 sources，
    # 不是 tool_count / source_count——早期按假设写的，已按真机改正。
    for key in ("duration_ms", "tool_calls", "sources", "stage_count", "cached", "answer_chars"):
        assert key in usage, f"usage 缺少字段：{key}"
    assert usage["tool_calls"] == len(resp["tool_calls"])
    assert usage["sources"] == len(resp["references"])
    assert usage["stage_count"] == len(resp["stages"])
    # 阶段是中文 key，不是英文 name
    assert [s["key"] for s in resp["stages"]] == ["调研", "综述", "方案", "报告"]


def test_usage_records_context_truncation(agent, trace):
    """v1.2 新增 usage.context：coverage 的分母有没有被上下文截断裁剪过。

    不记录这个，`coverage` 跨运行就不可比——C 的实测里 1.0 → 0.688 正是这个原因。
    """
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    ctx = resp["usage"].get("context")
    assert ctx is not None, "usage 缺少 context（v1.2 必填）"
    assert "truncated" in ctx, "context 必须带 truncated 标记"
    assert isinstance(ctx["truncated"], bool)
    # 真机叫 budget，不是 limit
    assert "budget" in ctx, f"context 缺 budget：{sorted(ctx)}"


def test_run_id_format(agent, trace):
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    run_id = resp["run_id"]
    assert run_id.startswith("eval-"), f"run_id 前缀不符：{run_id}"
    assert input is not None  # 占位，保持用例结构可读
    assert len(run_id) >= 18, f"run_id 过短：{run_id}"
