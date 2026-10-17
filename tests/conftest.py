"""用例级隔离。

被测系统在 pytest 路径下不会自己清结果缓存——C 的原话：他们的契约用例自带 runner，
每条前调 `api.clear_cache()`，但 pytest 直接收集 test_ 函数不走那段代码。
不隔离的话，后一条用例会命中前一条的缓存，断言假通过。
"""

from __future__ import annotations

import pytest


def _clear_result_cache() -> None:
    """仅在跑真实被测对象时才有缓存可清；本地替身没有缓存，直接跳过。"""
    try:
        from src.api import entry as api  # type: ignore[import-not-found]
    except ImportError:
        return
    api.clear_cache()


@pytest.fixture(autouse=True)
def _isolate_result_cache():
    _clear_result_cache()
    yield
    _clear_result_cache()
