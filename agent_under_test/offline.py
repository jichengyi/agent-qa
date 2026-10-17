"""离线打桩：把被测系统的外部依赖换成确定性假实现，流水线本身照常跑。

为什么不用 `MOCK_MODE=1`
------------------------
`MOCK_MODE` 会把检索整段短路（`research_flow.py:271` 的
`if not settings.MOCK and use_retrieval`），结果 `tool_calls=0`、`references=0`，
只能验结构、验不了行为。本模块反过来：**强制 `settings.MOCK = False`**，
让流水线真的走一遍检索，只是把联网 / 向量库 / 模型换成本地假数据。

代价：0 依赖、0 网络、0 模型额度，几十毫秒跑完。

用法
----
    from agent_under_test.offline import offline

    with offline(n_web=2, n_local=1):
        result = run("主题")

前置条件
--------
`PYTHONPATH` 指向被测系统源码根（该仓库没有 setup.py / pyproject.toml，
不能 pip install -e）。本模块的 import 全部延迟到调用时，未接入时不影响 pytest 收集。

来源：C 提供的《接口接入答疑》第 2 节，原样搬运，仅补注释。
"""

from __future__ import annotations

import contextlib
import time
from types import SimpleNamespace


def _paper(i: int):
    from src.rag.web_search import PaperRecord

    return PaperRecord(
        title=f"Paper {i}",
        abstract=f"Abstract {i}",
        year="2024",
        authors="A. Author",
        venue="Venue",
        doi=f"10.1/paper{i}",
        url=f"https://example.org/{i}",
        source="OpenAlex",
        cited_by=10 - i,
    )


@contextlib.contextmanager
def offline(
    n_web: int = 2,
    n_local: int = 1,
    n_know: int = 1,
    reply: str = "报告正文 [1]",
    sleep_s: float = 0.0,
    search_error: bool = False,
    chat_error: str = "",
):
    """跑完自动还原；进出都清缓存，避免用例之间串味。"""
    from config.settings import settings
    from src.api import entry as api
    from src.pipelines import research_flow as rf
    from src.rag import sources as src_mod
    from src.rag.web_search import SearchOutcome

    saved = {
        "mock": settings.MOCK,
        "chat": rf.chat_text,
        "build": rf.build_vectorstore,
        "retrieve": rf.retrieve,
        "knowledge": rf.local_knowledge.search_local_knowledge,
        "search": src_mod.search_papers_web,
    }

    def fake_chat(prompt, system=None):
        if chat_error:
            raise RuntimeError(chat_error)
        if sleep_s:
            time.sleep(sleep_s)
        if "科研调研助手" in prompt:
            return "调研：若干方向（未经本次检索核验）"
        if "文献综述专家" in prompt:
            return "综述：" + reply
        if "设计可行的研究/实验方案" in prompt:
            return "方案：" + reply
        if "整合为结构化研究报告" in prompt:
            return reply
        return "其他阶段输出"

    def fake_search(query, per_source=5, sources=None):
        if search_error:
            raise RuntimeError("HTTP 503：OpenAlex 限流")
        return SearchOutcome(
            records=[_paper(i) for i in range(1, n_web + 1)],
            per_source={"openalex": {"count": n_web, "error": ""}},
        )

    def fake_retrieve(vs, query, k=5):
        return [
            SimpleNamespace(
                page_content=f"本地片段 {i}",
                metadata={"source": f"paper{i}.pdf"},
            )
            for i in range(1, n_local + 1)
        ]

    def fake_knowledge(query, top_k=3):
        return [
            {
                "kind": "skill",
                "name": f"Skill {i}",
                "path": f"/skills/{i}",
                "desc": f"技能描述 {i}",
                "score": 1.0 - i * 0.1,
            }
            for i in range(1, n_know + 1)
        ]

    # 关键：让检索真的走一遍，只是工具是假的
    settings.MOCK = False
    rf.chat_text = fake_chat
    rf.build_vectorstore = lambda: object()
    rf.retrieve = fake_retrieve
    rf.local_knowledge.search_local_knowledge = fake_knowledge
    src_mod.search_papers_web = fake_search
    api.clear_cache()
    try:
        yield
    finally:
        settings.MOCK = saved["mock"]
        rf.chat_text = saved["chat"]
        rf.build_vectorstore = saved["build"]
        rf.retrieve = saved["retrieve"]
        rf.local_knowledge.search_local_knowledge = saved["knowledge"]
        src_mod.search_papers_web = saved["search"]
        api.clear_cache()
