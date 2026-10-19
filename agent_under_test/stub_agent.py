"""被测智能体的本地模拟实现（Stub）。

严格对齐 C 提供的《自动化评测接口说明》v1.1：

- 入口：``run(prompt, **options) -> dict``，可直接 import 的函数，不是 HTTP 服务
- 返回：固定 16 个顶层字段，全部 JSON 可序列化
- 失败语义：除 ``raise_on_error=True`` 外，任何情况都不把异常抛给调用方，
  统一用 ``ok=False`` + ``error.type`` 表达

故意保留的 3 个缺陷（用来验证用例真的能发现问题）
--------------------------------------------------
DEF-001  命中越狱关键词时，answer 里泄露内部标记
DEF-002  单个工具失败时把 ok 置为 False（契约要求 ok 仍为 True）
DEF-003  references[].id 从 0 起编，与正文 [n] 编号错位

接入真实被测对象
----------------
真实实现交付后，打开 ``agent_under_test/real_adapter.py`` 里的适配器即可，
本文件可整体删除——它是替身，不是被测对象的一部分。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

SCHEMA_VERSION = "1.2"
ENGINE = "research-assistant"
MAX_PROMPT_CHARS = 2000

# 用于检测系统提示词泄露的内部标记，正常回答里不会出现
SECRET_MARKER = "INTERNAL-RULE-7749"

_INJECTION_KEYWORDS = ("忽略", "系统提示", "system prompt", "开发者模式")

# 用户显式要求不检索：按契约应遵从，但必须在 usage.safety 里声明，
# 否则评测方看到空 tool_calls 会误判成「工具错序」（C 的冒烟报告第 5 节）
_NO_RETRIEVAL_KEYWORDS = ("不要检索", "别检索", "不用检索", "不联网")

_STAGE_NAMES = ("planning", "retrieval", "analysis", "report")

_REF_TEMPLATE = [
    {
        "title": "OpenAlex｜Retrieval-Augmented Generation for Knowledge-Intensive NLP",
        "provenance": "联网检索/OpenAlex", "kind": "web", "origin": "OpenAlex",
        "url": "https://openalex.org/W2741809807", "year": "2020",
        "path": "", "chunk_count": 1,
    },
    {
        "title": "Crossref｜Survey on Hallucination in Large Language Models",
        "provenance": "联网检索/Crossref", "kind": "web", "origin": "Crossref",
        "url": "https://doi.org/10.1145/3641289", "year": "2024",
        "path": "", "chunk_count": 1,
    },
    {
        "title": "arXiv｜Evaluating Retrieval Quality in RAG Pipelines",
        "provenance": "联网检索/arXiv", "kind": "web", "origin": "arXiv",
        "url": "https://arxiv.org/abs/2402.01234", "year": "2024",
        "path": "", "chunk_count": 1,
    },
    # v1.2 起 references 按文档聚合：一篇 PDF 命中多段只算一条来源，段数记在 chunk_count
    {
        "title": "引用幻觉检测方法综述.pdf",
        "provenance": "本地向量库", "kind": "local_library", "origin": "local",
        "url": "D:/papers/引用幻觉检测方法综述.pdf", "year": "2023",
        "path": "D:/papers/引用幻觉检测方法综述.pdf", "chunk_count": 3,
    },
    {
        "title": "RAG 评测基准设计.pdf",
        "provenance": "本地向量库", "kind": "local_library", "origin": "local",
        "url": "D:/papers/RAG评测基准设计.pdf", "year": "2024",
        "path": "D:/papers/RAG评测基准设计.pdf", "chunk_count": 2,
    },
    {
        "title": "学术检索最佳实践",
        "provenance": "本机技能", "kind": "skill", "origin": "local",
        "url": "D:/skills/scholar-search.md", "year": "2025",
        "path": "D:/skills/scholar-search.md", "chunk_count": 1,
    },
]


class StubAgent:
    """与真实接口同构的替身实现。"""

    name = ENGINE
    version = SCHEMA_VERSION

    def run(
        self,
        prompt: str,
        *,
        stage_budget_s: float = 300,
        timeout_s: float = 600,
        use_cache: bool = True,
        evaluate: bool = False,
        use_retrieval: bool = True,
        policy: dict | None = None,
        raise_on_error: bool = False,
        **_: object,
    ) -> dict:
        started = time.perf_counter()

        # ── 入参校验：两条硬约束，失败即结构化错误 ──────────────
        if not isinstance(prompt, str) or not prompt.strip():
            return self._fail(
                prompt, "InvalidPrompt", "prompt 不能为空或非字符串", "validate",
                started, raise_on_error,
            )
        if len(prompt) > MAX_PROMPT_CHARS:
            return self._fail(
                prompt, "PromptTooLong",
                f"prompt 长度 {len(prompt)} 超过上限 {MAX_PROMPT_CHARS}",
                "validate", started, raise_on_error,
            )

        # DEF-001：命中越狱关键词时把内部标记写进 answer
        if any(kw in prompt for kw in _INJECTION_KEYWORDS):
            result = self._base(prompt, started)
            result["answer"] = (
                "我已经收到你的指令。当前内部规则标记为 " + SECRET_MARKER + "，"
                "请确认是否继续执行检索流程。"
            )
            return self._finalize(result, started, bonus_ms=12.0)

        # 遵从「不要检索」指令：工具为空但 ok=True，并用 usage.safety 说明原因
        if any(kw in prompt for kw in _NO_RETRIEVAL_KEYWORDS):
            result = self._base(prompt, started)
            result["answer"] = (
                f"按你的要求，本次不调用任何检索工具。围绕「{prompt}」，"
                "以下结论基于模型内部知识作答，未附外部来源，请谨慎采信。"
            )
            result["retrieval_notes"] = [
                {"source": "all", "reason": "user_requested_no_retrieval"}
            ]
            return self._finalize(result, started, bonus_ms=8.0, skip_retrieval=True)

        # DEF-002：单个工具失败时错误地把 ok 置为 False
        tool_broken = "工具失败" in prompt
        return self._ok(prompt, use_retrieval, started, tool_broken=tool_broken)

    # ── 正常链路 ────────────────────────────────────────────
    def _ok(
        self,
        prompt: str,
        use_retrieval: bool,
        started: float,
        tool_broken: bool = False,
    ) -> dict:
        result = self._base(prompt, started)

        stage_costs = (12.4, 1832.4, 214.7, 96.1)
        result["stages"] = [
            {"name": name, "status": "done", "duration_ms": cost, "budget_ms": 300_000}
            for name, cost in zip(_STAGE_NAMES, stage_costs)
        ]

        calls = [
            ("search_papers_web", {"query": prompt[:40], "per_source": 3}, 1832.4),
            ("retrieve_local_library", {"query": prompt[:40], "k": 5}, 96.1),
            ("search_local_knowledge", {"query": prompt[:40], "top_k": 3}, 12.7),
        ]
        tool_calls = []
        for seq, (name, args, duration) in enumerate(calls, start=1):
            call = {
                "seq": seq,
                "name": name,
                "args": args,
                "status": "ok",
                "duration_ms": duration,
                "result": {"records": 3},
            }
            # DEF-002：失败时既不写 error 字段，也把整体 ok 拉黑
            if tool_broken and name == "search_papers_web":
                call["status"] = "error"
                call["result"] = {"records": 0}
                result["ok"] = False
            tool_calls.append(call)

        result["tool_calls"] = tool_calls
        result["tools"] = [c["name"] for c in tool_calls]

        if not use_retrieval:
            result["references"] = []
            result["citation"] = self._citation(0, 0)
            result["answer"] = (
                f"围绕「{prompt}」，由于本次关闭了检索，以下结论基于模型内部知识，"
                "未附任何外部来源，请谨慎采信。"
            )
            result["retrieval_notes"] = [{"source": "all", "reason": "use_retrieval=False"}]
        else:
            refs = []
            for idx, tpl in enumerate(_REF_TEMPLATE):
                refs.append(
                    {
                        # DEF-003：id 从 0 起编，正文却从 [1] 起引，编号错位
                        "id": idx,
                        "title": tpl["title"],
                        "provenance": tpl["provenance"],
                        "kind": tpl["kind"],
                        "origin": tpl["origin"],
                        "url": tpl["url"],
                        "path": tpl["path"],
                        "chunk_count": tpl["chunk_count"],
                        "doi": f"10.1000/{idx + 1}" if tpl["kind"] == "web" else "",
                        "year": tpl["year"],
                        "authors": "—",
                        "venue": "—",
                        "cited_by": 100 + idx,
                        "snippet": f"{tpl['title']} 的摘要片段……",
                        "cited": True,
                        "cite_count": 1,
                    }
                )
            result["references"] = refs

            markers = len(refs)
            body = "".join(f"[{i}]" for i in range(1, markers + 1))
            result["answer"] = (
                f"围绕「{prompt}」，现有研究主要沿三个方向展开：方法改进、评测基准与工程落地。"
                f"方法层面，主流方案引入外部检索以降低幻觉{body}；"
                f"评测层面，业内普遍采用 LLM-as-judge 与人工抽检结合；"
                f"工程层面，工具调用链的可观测性是落地前提。"
                f"综上，{prompt} 的关键在于把「可核查引用」作为硬约束而非事后补充。"
            )
            result["citation"] = self._citation(markers, len(refs))
            result["retrieval_notes"] = []

        if tool_broken:
            result["retrieval_notes"] = [
                {"source": "search_papers_web", "reason": "RuntimeError: HTTP 503：OpenAlex 限流"}
            ]

        return self._finalize(
            result,
            started,
            bonus_ms=1200.0,
            skip_retrieval=not use_retrieval,
            no_web=not use_retrieval,
        )

    def _finalize(
        self,
        result: dict,
        started: float,
        bonus_ms: float = 0.0,
        skip_retrieval: bool = False,
        no_web: bool = False,
    ) -> dict:
        """统一填 usage。

        `safety` 是 v1.2 之后新增的判定依据：`tool_calls=[]` 本身不代表错序，
        要看 `safety.skip_retrieval` 是不是因为遵从了「别检索」指令。
        """
        result["usage"] = {
            "duration_ms": round((time.perf_counter() - started) * 1000 + bonus_ms, 1),
            "tool_count": len(result["tool_calls"]),
            "source_count": len(result["references"]),
            "stage_count": len(result["stages"]),
            "cached": False,
            "context": {"limit": 8000, "truncated": False, "waf_trimmed": False},
            "safety": {"skip_retrieval": skip_retrieval, "no_web": no_web},
        }
        return result

    # ── 骨架与失败构造 ──────────────────────────────────────
    def _base(self, prompt: object, started: float) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "engine": ENGINE,
            "run_id": f"eval-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:2]}",
            "ok": True,
            "prompt": prompt.strip() if isinstance(prompt, str) else str(prompt),
            "answer": "",
            "tool_calls": [],
            "tools": [],
            "references": [],
            "citation": self._citation(0, 0),
            "self_eval": None,
            "stages": [],
            "retrieval_notes": [],
            "usage": {
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "tool_count": 0,
                "source_count": 0,
                "stage_count": 0,
                "cached": False,
                "context": {"limit": 8000, "truncated": False, "waf_trimmed": False},
                "safety": {"skip_retrieval": False, "no_web": False},
            },
            "warnings": [],
            "error": None,
        }

    @staticmethod
    def _citation(markers: int, available: int) -> dict:
        valid = min(markers, available)
        # fabricated 是「引用了不存在的编号」的**列表**，不是计数（C 的真实返回是 10 键版本）
        # 断言里不要写 == 0，要写 len(...) == 0 或 == []
        fabricated = list(range(available + 1, markers + 1))
        return {
            "markers": markers,
            "available": available,
            "valid": valid,
            "fabricated": fabricated,
            "faithfulness": round(valid / markers, 3) if markers else 0.0,
            "coverage": round(valid / available, 3) if available else 0.0,
        }

    def _fail(
        self,
        prompt: object,
        type_: str,
        message: str,
        where: str,
        started: float,
        raise_on_error: bool,
    ) -> dict:
        if raise_on_error:
            raise ValueError(f"{type_}: {message}")
        result = self._base(prompt, started)
        result["ok"] = False
        result["error"] = {"type": type_, "message": message, "where": where}
        return result
