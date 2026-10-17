"""冒烟用例：主干链路能不能走通。

这批用例对应「第 1 周跑通 10 条基础用例」里最基础的一半，
每条都通过 trace.record 留痕，供 B 的 judge 事后复评。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke


@pytest.mark.parametrize(
    "topic",
    ["大模型幻觉检测", "RAG 系统的引用可靠性", "智能体工具调用评测"],
)
def test_returns_non_empty_answer(agent, trace, topic):
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    assert resp["answer"].strip(), "回答为空"
    assert len(resp["answer"]) >= 20, f"回答过短：{len(resp['answer'])} 字"


def test_answer_mentions_topic(agent, trace):
    topic = "大模型幻觉检测"
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    assert topic in resp["answer"], "回答未回扣用户主题"


def test_response_latency(agent, trace):
    topic = "智能体工具调用评测"
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    assert resp["elapsed_ms"] < 3000, f"响应过慢：{resp['elapsed_ms']} ms"


def test_tool_call_chain(agent, trace):
    topic = "智能体工具调用评测"
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    tools = [call["tool"] for call in resp["tool_calls"]]
    assert tools == ["search", "fetch", "summarize"], f"工具链顺序异常：{tools}"
