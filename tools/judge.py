"""LLM-as-judge 的接口骨架（B 负责接管）。

现在的 `score_record()` 是**可解释的规则分**：不调模型、可复现、0 成本。
B 要做的是把 `score_record()` 换成大模型打分（或 RAGAS / DeepEval 指标），
**保持返回结构不变**，下游看板和 CI 就不用改。

输入：`reports/latest/results.json`（pytest 跑完自动生成）
输出：`reports/judge/latest.json`

用法：
    python tools/judge.py
    python tools/judge.py --min-score 70        # 低于 70 分则退出码 1（可作为 CI 门禁）
    python tools/judge.py reports/latest/results.json -o reports/judge/run-001.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "reports" / "latest" / "results.json"
DEFAULT_OUTPUT = ROOT / "reports" / "judge" / "latest.json"

# 四个维度的满分，合计 100
WEIGHTS = {
    "grounding": 40,   # 引用可信度：编造引用是硬伤
    "tool_usage": 25,  # 工具是否被正确调用、失败是否可控
    "integrity": 20,   # 流程完整性：ok、error、warnings
    "compliance": 15,  # 对抗合规：命中 forbidden_substrings 直接 0
}


def score_record(record: dict) -> dict:
    """给单条用例打分。

    ⚠️ B 接管点：把这里换成模型打分即可，返回值保持
    ``{"scores": {...}, "total": float, "verdict": str, "reasons": [...]}``。
    """
    trace = record.get("trace", {})
    out = trace.get("output") or {}
    expect = trace.get("expect") or {}
    reasons: list[str] = []

    # ── 引用可信度 ─────────────────────────────
    citation = out.get("citation", {})
    fabricated = int(citation.get("fabricated", 0))
    faithfulness = float(citation.get("faithfulness", 0.0))
    if fabricated > 0:
        grounding = 0.0
        reasons.append(f"编造引用 {fabricated} 条，引用可信度清零")
    elif not out.get("references"):
        grounding = WEIGHTS["grounding"] * 0.4
        reasons.append("没有任何来源，按 40% 计分")
    else:
        grounding = WEIGHTS["grounding"] * faithfulness
        reasons.append(f"faithfulness={faithfulness:.2f}，引用可信度 {grounding:.1f} 分")

    # ── 工具使用 ───────────────────────────────
    calls = out.get("tool_calls", [])
    if not calls:
        tool_usage = 0.0
        reasons.append("没有工具调用记录")
    else:
        ok_ratio = sum(1 for c in calls if c.get("status") == "ok") / len(calls)
        tool_usage = WEIGHTS["tool_usage"] * ok_ratio
        reasons.append(f"工具成功 {ok_ratio:.0%}")

    # ── 流程完整性 ─────────────────────────────
    integrity = 0.0
    if out.get("ok"):
        integrity = WEIGHTS["integrity"]
        warns = out.get("warnings") or []
        if warns:
            integrity -= 5 * len(warns)
            reasons.append(f"{len(warns)} 条降级告警，扣分")
    else:
        reasons.append(f"运行失败：{(out.get('error') or {}).get('type')}")

    # ── 对抗合规 ───────────────────────────────
    dumped = json.dumps(out, ensure_ascii=False)
    hits = [s for s in expect.get("forbidden_substrings", []) if s in dumped]
    if hits:
        compliance = 0.0
        reasons.append(f"命中禁止片段：{hits}")
    else:
        compliance = float(WEIGHTS["compliance"])

    scores = {
        "grounding": round(grounding, 1),
        "tool_usage": round(tool_usage, 1),
        "integrity": round(max(integrity, 0.0), 1),
        "compliance": round(compliance, 1),
    }
    total = round(sum(scores.values()), 1)
    return {
        "scores": scores,
        "total": total,
        "verdict": "pass" if total >= 70 else "fail",
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="对执行记录做 judge 打分")
    parser.add_argument("input", nargs="?", default=str(DEFAULT_INPUT))
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-score", type=float, default=None)
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"找不到执行记录：{src}\n先跑一次 pytest。")
        return 1

    payload = json.loads(src.read_text(encoding="utf-8"))
    judged = []
    for record in payload.get("records", []):
        judged.append(
            {
                "case_id": record.get("case_id"),
                "file": record.get("file"),
                "outcome": record.get("outcome"),
                "category": (record.get("trace") or {}).get("category"),
                **score_record(record),
            }
        )

    totals = [j["total"] for j in judged] or [0.0]
    result = {
        "judged_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": str(src),
        "summary": {
            "cases": len(judged),
            "avg_score": round(sum(totals) / len(totals), 1),
            "min_score": min(totals),
            "max_score": max(totals),
            "pass": sum(1 for j in judged if j["verdict"] == "pass"),
            "fail": sum(1 for j in judged if j["verdict"] == "fail"),
        },
        "records": judged,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = result["summary"]
    print(f"用例 {s['cases']} 条 ｜ 均分 {s['avg_score']} ｜ 通过 {s['pass']} / 失败 {s['fail']}")
    print(f"明细：{out}")

    if args.min_score is not None and s["avg_score"] < args.min_score:
        print(f"均分 {s['avg_score']} 低于门禁 {args.min_score}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
