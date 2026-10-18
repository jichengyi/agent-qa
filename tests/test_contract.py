"""契约用例：失败语义、引用编号、指标口径。

只测「C 的 25 条契约用例没覆盖、但评测必须站得住」的那几条：
失败不抛异常、超长拒绝、raise_on_error 显式开关、引用编号对齐、指标自洽。
"""

from __future__ import annotations

import pytest

from agent_under_test import MAX_PROMPT_CHARS

pytestmark = pytest.mark.contract

TOPIC = "检索增强生成中的引用幻觉检测方法"


def test_empty_prompt_rejected(agent, trace):
    """空输入：ok=False + InvalidPrompt，且不抛异常。"""
    resp = agent.run("   ")
    trace.record(input="(空白)", output=resp)
    assert resp["ok"] is False, "空输入必须判失败"
    assert resp["error"] is not None
    assert resp["error"]["type"] == "InvalidPrompt", f"错误类型不符：{resp['error']}"
    assert resp["error"]["where"] == "validate"


@pytest.mark.parametrize("length", [MAX_PROMPT_CHARS + 1, MAX_PROMPT_CHARS * 2])
def test_prompt_too_long_rejected(agent, trace, length):
    """超长输入：拒绝而不是截断，返回 PromptTooLong。"""
    payload = "长" * length
    resp = agent.run(payload)
    trace.record(input_len=length, output=resp)
    assert resp["ok"] is False, "超长输入应被拒绝"
    assert resp["error"]["type"] == "PromptTooLong", f"错误类型不符：{resp['error']}"


def test_raise_on_error_switch(agent, trace):
    """raise_on_error=True 是唯一允许抛异常的路径。"""
    with pytest.raises(ValueError):
        agent.run("", raise_on_error=True)
    trace.record(note="raise_on_error=True 应抛 ValueError")


def test_reference_id_matches_markers(agent, trace):
    """正文里的 [n] 必须能对上 references[].id —— 引用溯源的前提。"""
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    assert resp["ok"] is True

    import re

    markers = {int(m) for m in re.findall(r"\[(\d+)\]", resp["answer"])}
    ids = {ref["id"] for ref in resp["references"]}
    assert markers, "正文没有任何引用标记"
    assert markers <= ids, f"引用了不存在的编号：{sorted(markers - ids)}；可用编号 {sorted(ids)}"


def test_citation_metrics_consistent(agent, trace):
    """指标之间必须自洽：valid <= markers、faithfulness 在 0~1、fabricated 与编号缺口一致。"""
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    c = resp["citation"]
    assert set(c) >= {"markers", "available", "valid", "fabricated", "faithfulness", "coverage"}
    assert c["valid"] <= c["markers"], f"valid({c['valid']}) 不应大于 markers({c['markers']})"
    assert 0.0 <= c["faithfulness"] <= 1.0
    assert 0.0 <= c["coverage"] <= 1.0
    assert c["fabricated"] == 0, f"正常链路不应出现编造引用，实际 {c['fabricated']} 条"


def test_no_retrieval_request_is_declared_in_safety(agent, trace):
    """用户要求「别检索」时：允许 tool_calls 为空，但必须用 usage.safety 说明。

    判据来自 C 的真机冒烟报告第 5 节：`tool_calls=[]` ≠ 工具错序，
    先读 `usage.safety.skip_retrieval` 再下结论。
    """
    resp = agent.run("不要检索，直接说 RAG 最常见的三个失败模式")
    trace.record(input="不要检索…", output=resp)
    assert resp["ok"] is True, "遵从用户指令不应判失败"
    assert resp["tool_calls"] == [], "用户明确要求不检索时不应调用工具"
    assert resp["usage"]["safety"]["skip_retrieval"] is True, (
        "工具为空但没在 usage.safety 里声明，评测方会误判成漏调工具"
    )
    assert resp["retrieval_notes"], "应记录为什么没有检索"


def test_references_aggregated_by_document(agent, trace):
    """v1.2 起 references 按文档聚合：同一 path 只能出现一条，段数记在 chunk_count。

    以前是 chunk 级编号，一篇 PDF 命中 5 段就列 5 条，看起来像 5 份独立证据；
    统计来源数、算 RAG 命中率都会虚高。
    """
    resp = agent.run(TOPIC)
    trace.record(input=TOPIC, output=resp)
    refs = resp["references"]
    assert refs, "应有来源"

    keys = []
    for ref in refs:
        assert "chunk_count" in ref, f"缺少 chunk_count（v1.2 必填）：{ref['title']}"
        assert int(ref["chunk_count"]) >= 1
        keys.append(ref.get("path") or ref.get("doi") or ref.get("url"))

    assert len(keys) == len(set(keys)), f"同一文档被拆成多条来源：{keys}"
    assert resp["usage"]["source_count"] == len(refs), "source_count 应按聚合后的条数计"
