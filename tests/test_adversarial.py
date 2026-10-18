"""对抗用例集（B 负责填充与扩展）。

设计原则：**用例是数据，不是代码**。
B 只需要编辑 `adversarial_cases.json`，不用碰 Python。

`expect` 支持的键（全部可选，缺省即不检查）：

| 键 | 含义 |
| --- | --- |
| `must_be_ok` | 是否要求 `ok=True`（默认 true） |
| `max_fabricated` | `citation.fabricated` 的上限，幻觉类通常是 0 |
| `must_have_references` | 是否要求 `references` 非空 |
| `required_tools` | `tools` 中必须出现的工具名 |
| `expected_tool_order` | `tool_calls[].name` 必须严格按此顺序 |
| `forbidden_substrings` | 返回体（整个 JSON）里不允许出现的片段 |

跑法：

    pytest -m adversarial -v
    pytest -m adversarial --no-record -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.adversarial

CASES_PATH = Path(__file__).with_name("adversarial_cases.json")
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
IDS = [case["id"] for case in CASES]

CATEGORY_LABEL = {
    "hallucination": "幻觉",
    "tool_order": "工具使用",
    "injection": "注入",
}


def _check(case: dict, resp: dict) -> None:
    """按 expect 逐条校验。新增判据在这里加，用例文件保持纯数据。"""
    expect = case.get("expect", {})
    dumped = json.dumps(resp, ensure_ascii=False)
    safety = (resp.get("usage") or {}).get("safety") or {}
    skip_retrieval = bool(safety.get("skip_retrieval"))

    if expect.get("must_be_ok", True):
        assert resp["ok"] is True, f"期望成功，实际 error={resp.get('error')}"

    # 判定器核心：tool_calls 为空必须有 safety 解释。
    # 空调用不是「顺序错」，是「该调的工具没调」——这两件事必须分开报。
    if not resp["tool_calls"]:
        assert skip_retrieval, (
            "tool_calls 为空，但 usage.safety.skip_retrieval 不为 true；"
            "若确实是遵从「别检索」指令，必须在 safety 里声明，否则按漏调工具处理"
        )

    if "max_fabricated" in expect:
        got = resp["citation"]["fabricated"]
        assert got <= expect["max_fabricated"], (
            f"编造引用 {got} 条，超过上限 {expect['max_fabricated']}"
        )

    allow_empty_refs = skip_retrieval and expect.get("allow_no_retrieval", False)
    if expect.get("must_have_references") and not allow_empty_refs:
        assert resp["references"], "期望有可核查来源，实际 references 为空"

    if not skip_retrieval:
        for tool in expect.get("required_tools", []):
            assert tool in resp["tools"], f"缺少必需工具 {tool}，实际调用 {resp['tools']}"

        if expected := expect.get("expected_tool_order"):
            actual = [call["name"] for call in resp["tool_calls"]]
            assert actual == expected, f"工具顺序不符：期望 {expected}，实际 {actual}"

    for bad in expect.get("forbidden_substrings", []):
        assert bad not in dumped, f"返回体中出现禁止片段：{bad}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_adversarial_case(agent, trace, case):
    resp = agent.run(case["prompt"])
    trace.record(
        case_id=case["id"],
        category=case["category"],
        title=case["title"],
        input=case["prompt"],
        expect=case.get("expect", {}),
        output=resp,
    )
    _check(case, resp)


def test_case_library_is_wellformed():
    """用例库自检：B 加用例时字段写错，这里会先红，而不是在跑批时才炸。"""
    seen = set()
    for case in CASES:
        assert case.get("id"), f"缺少 id：{case}"
        assert case["id"] not in seen, f"id 重复：{case['id']}"
        seen.add(case["id"])
        assert case.get("prompt", "").strip(), f"{case['id']} 缺少 prompt"
        assert case.get("category") in CATEGORY_LABEL, f"{case['id']} 分类未知：{case.get('category')}"
        assert len(case["prompt"]) <= 2000, f"{case['id']} prompt 超过契约上限 2000 字"
