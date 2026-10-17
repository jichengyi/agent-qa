"""被测对象包。真实项目接入后，这里只保留客户端封装，不再放 Agent 实现。"""

from .stub_agent import SECRET_MARKER, SYSTEM_PROMPT, TOOL_CHAIN, StubAgent

__all__ = ["StubAgent", "SYSTEM_PROMPT", "SECRET_MARKER", "TOOL_CHAIN"]
