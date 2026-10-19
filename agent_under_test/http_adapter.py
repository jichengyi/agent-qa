"""HTTP 适配器：把 C 的评测 API 包成与 StubAgent 同形状的对象。

背景
----
早期 C 交付的是「可 import 的源码」（``src.api.run``），对应 ``real_adapter.py``。
现在 C 把被测系统挂成了 HTTP 服务（8765 平台 / 8501 人工体验 / 8610 MOCK 通道 /
8600 云 LLM 真实链路），评测侧改成打接口，不再碰源码。

两种接入方式并存，用环境变量区分：

============================  ========================================
``AGENT_IMPL=http``          打 HTTP 接口（本文档，对应 C 的平台）
``AGENT_IMPL=real``          import 源码（``real_adapter.py``，保留兼容）
不设                          本地替身 ``StubAgent``
============================  ========================================

用法::

    set AGENT_IMPL=http
    set AGENT_ENDPOINT=http://10.225.252.61:8610/chat    # 8610 不耗额度
    pytest -m "contract or adversarial"

设计约束（踩过的坑）
--------------------
1. **网络故障与业务失败必须分开。**
   连不上/超时属于环境问题，若包装成 ``ok=False``，39 条用例会一起变红，
   读起来像是被测系统崩了。所以这里抛 ``TransportError``，pytest 记
   ``error`` 而不是 ``failed``，一眼能分辨。
2. **批量评测一律 ``use_cache=False``。**
   HTTP 通道实测有效（缺省会命中缓存，第二次 ``usage.cached=true``）。
   ``conftest._Agent`` 已经统一注入，这里不用重复。
3. **未知参数会被服务端静默忽略。**
   实测传 ``{"不存在的参数": 1}`` 返回 ``ok=true``，不会报错。
   所以这里只转发已知白名单，避免拼错的参数名悄悄不生效。
4. **错误走 HTTP 200 + body 里的 ``error``。**
   空输入、超长输入、缺字段，实测都是 200。判定失败要读 ``ok``，别看状态码。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# 服务端认识的可选参数。不在表里的评测侧参数一律不发。
FORWARDED_OPTIONS = (
    "use_cache",
    "stage_budget_s",
    "timeout_s",
    "evaluate",
    "use_retrieval",
    "policy",
)

DEFAULT_ENDPOINT = "http://127.0.0.1:8610/chat"
DEFAULT_TIMEOUT_S = 300.0

# raise_on_error=True 时，把 error.type 还原成对应的异常类。
# HTTP 层只剩字符串，不映射的话只能一律抛 RuntimeError，跟源码版语义对不上。
ERROR_EXCEPTIONS: dict[str, type[Exception]] = {
    "InvalidPrompt": ValueError,
    "PromptTooLong": ValueError,
    "TimeoutError": TimeoutError,
}


class TransportError(RuntimeError):
    """网络层故障：连不上、超时、响应不是 JSON 对象。

    刻意不伪装成 ``ok=False`` —— 那是被测系统的缺陷语义。
    """


class HttpAgent:
    """把评测 API 包成 ``run(prompt, **options) -> dict``。"""

    def __init__(self, endpoint: str | None = None, timeout_s: float | None = None) -> None:
        self.endpoint = (
            endpoint
            or os.environ.get("AGENT_ENDPOINT", "").strip()
            or DEFAULT_ENDPOINT
        )
        raw_timeout = timeout_s if timeout_s is not None else os.environ.get("AGENT_HTTP_TIMEOUT")
        try:
            self.timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
        except (TypeError, ValueError):
            self.timeout_s = DEFAULT_TIMEOUT_S

        self.name = "research-assistant"
        self.version = "http"
        self.mode = "http"

    def health(self) -> dict:
        """探活：命中 ``/health``（存在时返回引擎与缓存状态）。

        失败返回 ``{"ok": False, "error": ...}``，不抛 —— 探活本身就是用来
        判断「要不要跑」的，抛异常反而不好用。
        """
        base = self.endpoint.rsplit("/", 1)[0]
        url = f"{base}/health"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.load(resp)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}

    def run(self, prompt: str, **options: object) -> dict:
        raise_on_error = bool(options.pop("raise_on_error", False))

        body: dict = {"prompt": prompt}
        for key in FORWARDED_OPTIONS:
            if key in options:
                body[key] = options.pop(key)

        payload = self._post(body)

        if raise_on_error and not payload.get("ok"):
            err = payload.get("error") or {}
            err_type = str(err.get("type", "Unknown"))
            exc_class = ERROR_EXCEPTIONS.get(err_type, RuntimeError)
            raise exc_class(f"{err_type}: {err.get('message', '')}")
        return payload

    def _post(self, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # 服务端用了非 2xx：先看 body 是不是结构完整的契约返回，
            # 是就交给用例去判（可能是它自己的设计），不是就是协议被破坏了。
            raw = exc.read() if hasattr(exc, "read") else b""
            payload = _try_json(raw)
            if isinstance(payload, dict) and "ok" in payload:
                return payload
            raise TransportError(
                f"HTTP {exc.code} 且响应不是契约结构，前 200 字：{raw[:200]!r}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TransportError(
                f"连不上 {self.endpoint}：{exc.reason}。"
                "确认 C 的电脑开着、服务已起、防火墙放行端口、IP 没变。"
            ) from exc
        except TimeoutError as exc:
            raise TransportError(
                f"请求 {self.endpoint} 超时（{self.timeout_s}s）。"
                "真实链路单条约 1000s，需要时调大 AGENT_HTTP_TIMEOUT。"
            ) from exc

        payload = _try_json(raw)
        if not isinstance(payload, dict):
            raise TransportError(
                f"响应不是 JSON 对象（HTTP {status}），前 200 字：{raw[:200]!r}"
            )
        return payload


def _try_json(raw: bytes) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
