"""读取执行记录，打印汇总表；在 GitHub Actions 里同时写入 Job Summary。

用法：
    python tools/summary.py                      # 读 reports/latest/results.json
    python tools/summary.py path/to/results.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT = Path("reports") / "latest" / "results.json"


def render(payload: dict) -> str:
    s = payload.get("summary", {})
    lines = [
        "## 测试执行汇总",
        "",
        f"- 运行时间：{payload.get('run_at', '未知')}",
        f"- 用例总数：{s.get('total', 0)}",
        f"- 通过 / 失败 / 错误 / 跳过：{s.get('passed', 0)} / {s.get('failed', 0)} / "
        f"{s.get('error', 0)} / {s.get('skipped', 0)}",
        f"- **通过率：{s.get('pass_rate', 0)}%**",
        f"- 总耗时：{s.get('duration_s', 0)} s",
        "",
        "### 失败明细",
        "",
    ]

    failed = [r for r in payload.get("records", []) if r.get("outcome") != "passed"]
    if failed:
        lines.append("| 用例 | 结果 | 耗时(s) |")
        lines.append("| --- | --- | --- |")
        for r in failed:
            lines.append(f"| `{r['case_id']}` | {r['outcome']} | {r['duration_s']} |")
    else:
        lines.append("全部通过。")

    return "\n".join(lines)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"找不到执行记录：{path}", file=sys.stderr)
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    text = render(payload)
    print(text)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
