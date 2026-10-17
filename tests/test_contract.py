"""契约用例：输出结构、引用合规、错误码。

判断标准来自「一个可交付的科研助手应该长什么样」，而不是实现细节。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract

TRUSTED_DOMAINS = ("arxiv.org", "doi.org", "nature.com", "acm.org", "ieee.org", "cnki.net")


def test_empty_topic_should_raise(agent, trace):
    """空主题应明确拒绝（抛 ValueError），而不是编一段看起来像答案的话。"""
    with pytest.raises((ValueError, TypeError)):
        resp = agent.answer("")
        trace.record(input="", output=resp)


def test_citation_schema(agent, trace):
    topic = "RAG 系统的引用可靠性"
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    assert resp["citations"], "回答没有任何引用"
    for item in resp["citations"]:
        assert item.get("title"), f"引用缺少标题：{item}"
        assert str(item.get("url", "")).startswith("http"), f"引用缺少合法链接：{item}"


def test_citation_domain_is_trusted(agent, trace):
    topic = "智能体评测方法"
    resp = agent.answer(topic)
    trace.record(input=topic, output=resp)
    untrusted = [
        c["url"] for c in resp["citations"] if not any(d in c["url"] for d in TRUSTED_DOMAINS)
    ]
    assert not untrusted, f"引用来源不可信：{untrusted}"
