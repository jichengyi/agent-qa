"""被测对象包。

- ``stub_agent.StubAgent``：本地替身，与真实接口同构，用来先把链路跑通
- ``real_adapter.RealAgent``：真实实现的适配器，交付后把 conftest 切过去即可
"""

from .stub_agent import MAX_PROMPT_CHARS, SCHEMA_VERSION, SECRET_MARKER, StubAgent

__all__ = ["StubAgent", "SCHEMA_VERSION", "MAX_PROMPT_CHARS", "SECRET_MARKER"]
