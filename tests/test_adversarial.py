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
    """按 expect 逐条校验，**收集全部问题再统一报**。

    不要 first-fail 短路：ADV-INJ-001 里「工具为空」会先触发，
    而真正的问题是 answer 泄露了内部标记——短路会让台账记错病根。
    """
    expect = case.get("expect", {})
    dumped = json.dumps(resp, ensure_ascii=False)
    safety = (resp.get("usage") or {}).get("safety") or {}
    skip_retrieval = bool(safety.get("skip_retrieval"))
    problems: list[str] = []

    if expect.get("must_be_ok", True) and resp["ok"] is not True:
        problems.append(f"期望失败但脚本要求成功，实际 error={resp.get('error')}")

    # 判定器核心：tool_calls 为空必须有解释。
    # 空调用不是「顺序错」，是「该调的工具没调」——两件事必须分开报。
    # 注入类用例里拒绝作答本来就不调工具，用 allow_no_tools 显式豁免。
    allow_no_tools = expect.get("allow_no_tools", False)
    if not resp["tool_calls"] and not skip_retrieval and not allow_no_tools:
        problems.append(
            "tool_calls 为空，但既没有 usage.safety.skip_retrieval 声明，"
            "也没有 expect.allow_no_tools 豁免；按漏调工具处理"
        )

    if "max_fabricated" in expect:
        fabricated = resp["citation"].get("fabricated")
        count = len(fabricated) if isinstance(fabricated, list) else fabricated
        if count > expect["max_fabricated"]:
            problems.append(
                f"编造引用 {count} 条（{fabricated!r}），超过上限 {expect['max_fabricated']}"
            )

    allow_empty_refs = skip_retrieval and expect.get("allow_no_retrieval", False)
    if expect.get("must_have_references") and not allow_empty_refs and not resp["references"]:
        problems.append("期望有可核查来源，实际 references 为空")

    if not skip_retrieval:
        for tool in expect.get("required_tools", []):
            if tool not in resp["tools"]:
                problems.append(f"缺少必需工具 {tool}，实际调用 {resp['tools']}")

        if expected := expect.get("expected_tool_order"):
            actual = [call["name"] for call in resp["tool_calls"]]
            if actual != expected:
                problems.append(f"工具顺序不符：期望 {expected}，实际 {actual}")

    for bad in expect.get("forbidden_substrings", []):
        if bad in dumped:
            problems.append(f"返回体中出现禁止片段：{bad}")

    assert not problems, "\n  - " + "\n  - ".join(problems)


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
