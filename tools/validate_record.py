"""校验 reports/latest/results.json 是否符合格式契约。

生产端（conftest）写完会自检一次，CI 再校验一次。
**字段一旦改名，这里先红**——别等到 C 的看板崩了才发现。

用法：
    python tools/validate_record.py
    python tools/validate_record.py path/to/results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.record_schema import FORMAT_VERSION, validate_payload  # noqa: E402

DEFAULT = ROOT / "reports" / "latest" / "results.json"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"找不到执行记录：{path}\n先跑一次 pytest。")
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_payload(payload)

    if errors:
        print(f"✗ 执行记录格式校验失败（契约 v{FORMAT_VERSION}），共 {len(errors)} 处：\n")
        for err in errors:
            print(f"  - {err}")
        print(
            "\n处理原则：字段只增不减。要加字段，先在 tools/record_schema.py 登记，"
            "再通知 B 和 C。"
        )
        return 1

    total = payload["summary"]["total"]
    print(f"✓ 执行记录格式校验通过（契约 v{FORMAT_VERSION}，{total} 条记录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
