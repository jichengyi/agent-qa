"""真实被测对象的适配器。

C 交付科研助手之后，只改这一处：把 ``src.api.run`` 导进来，其余代码一行不动。

用法（二选一）
--------------
1. 环境变量切换（推荐，ci 里也好用）::

       set AGENT_IMPL=real
       set AGENT_SRC=D:\\workAi\\research-assistant     # 科研助手源码根目录
       pytest

2. 直接改 conftest.py 的 agent fixture，让它 return RealAgent()

约定：适配器只做「调用 + 兜底转 dict」，不复制任何业务逻辑。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class RealAgent:
    """把 ``src.api.run`` 包成与 StubAgent 同形状的对象。"""

    name = "research-assistant"
    version = "1.1"

    def __init__(self, src_root: str | None = None) -> None:
        root = src_root or os.environ.get("AGENT_SRC")
        if root:
            path = str(Path(root).expanduser().resolve())
            if path not in sys.path:
                sys.path.insert(0, path)

        try:
            from src.api import run as _run  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - 仅在未交付时触发
            raise RuntimeError(
                "找不到 src.api.run。请设置环境变量 AGENT_SRC 指向科研助手源码根目录，"
                "或确认该工程已 pip install -e ."
            ) from exc

        self._run = _run

    def run(self, prompt: str, **options: object) -> dict:
        return self._run(prompt, **options)
