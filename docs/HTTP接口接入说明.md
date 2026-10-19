# HTTP 接口接入说明

> 2026-10-19 起，被测对象从「可 import 的源码」变成「C 搭好的 HTTP 服务」。
> 本文记录接入方式、实测口径和已知限制。契约字段以《接口契约速查.md》为准。

## 一、四个入口

| 地址 | 是什么 | 用途 |
| --- | --- | --- |
| `http://10.225.252.61:8765` | EduGuard 测试平台（Streamlit） | C 的演示看板，A/B 可用浏览器体验 |
| `http://10.225.252.61:8501` | 被测系统本体（人工体验） | 复现报告里的缺陷 |
| `http://10.225.252.61:8610/chat` | 评测 API · **MOCK 稳定通道** | 契约测试，不耗额度、不要密钥 |
| `http://10.225.252.61:8600/chat` | 评测 API · **云 LLM 真实链路** | 行为测试（工具调用、引用），可能限流 |

探活：`GET /health` 返回
`{"ok": true, "engine": "research-assistant", "schema_version": "1.2", "cache": {"size":1,"maxsize":32}, "max_concurrent": 2}`。

## 二、三种被测对象模式

```bash
# ① 本地替身（默认，不用网络，随时可跑，故意保留 3 个缺陷）
.venv/Scripts/python.exe -m pytest -q

# ② HTTP 接口（打 C 的服务）
AGENT_IMPL=http AGENT_ENDPOINT=http://10.225.252.61:8610/chat .venv/Scripts/python.exe -m pytest -q

# ③ 源码 import（旧方式，C 给源码时才用）
AGENT_IMPL=real AGENT_SRC=D:/workAi/research-assistant .venv/Scripts/python.exe -m pytest -q
```

可选环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AGENT_ENDPOINT` | `http://127.0.0.1:8610/chat` | 接口地址 |
| `AGENT_HTTP_TIMEOUT` | `300` | 单次请求超时（秒）。真实链路单条约 1000s，跑 8600 时建议调到 1800 |

## 三、8610 与 8600 能测的范围不一样，别混

这是接入后实测出来的硬边界（2026-10-19）：

| | 8610 MOCK 通道 | 8600 真实链路 |
| --- | --- | --- |
| 字段契约 / 错误语义 | ✅ 可测 | ✅ 可测 |
| `tool_calls` | ❌ 恒为空（检索被短路） | ✅ 有 3 个工具 |
| `references` | ❌ 恒为空 | ✅ 有 10 条来源 |
| `citation` 指标 | ❌ 全零，无意义 | ✅ 有意义（不失败时） |
| 额度 | 不耗 | 耗，会限流 |

实测基线（MOCK 通道，40 条用例）：

```
28 passed, 11 failed, 1 skipped
```

**这 11 个失败不是缺陷**，全部源于「MOCK 不检索」：
幻觉类 3 条（无 references 可判）、工具类 2 条（tool_calls 为空）、
注入类 1 条（依赖工具链）、引用对齐 2 条、降级行为 1 条、稳定性 1 条、工具顺序 1 条。

所以跑批命令要分开：

```bash
# 日常 / CI：只跑契约与冒烟（MOCK 通道足够）
AGENT_IMPL=http AGENT_ENDPOINT=http://10.225.252.61:8610/chat \
  .venv/Scripts/python.exe -m pytest -m "contract or smoke" -q

# 行为验收：真实链路（限流时只能跑少量）
AGENT_IMPL=http AGENT_ENDPOINT=http://10.225.252.61:8600/chat AGENT_HTTP_TIMEOUT=1800 \
  .venv/Scripts/python.exe -m pytest -m "safety or adversarial" -q
```

## 四、自动跳过的用例

`needs_injection` 标记的用例在 HTTP 模式下**自动跳过**，理由是跨网络改不了对端进程里的函数行为：

```
SKIPPED [1] tests/test_safety.py:33: HTTP 通道无法注入进程内故障；去掉 AGENT_IMPL=http 用本地替身跑这条
```

目前只有 `test_search_source_503_keeps_ok_true_and_has_references` 一条。
要验证「单源失败不改 ok」，用本地替身跑。

## 五、HTTP 适配器的三条设计决策

写在 `agent_under_test/http_adapter.py`，改动前先读那段 docstring：

1. **网络故障抛 `TransportError`，不伪装成 `ok=False`。**
   否则网线一拔，全部用例一起变红，读起来像被测系统崩了。
   抛异常时 pytest 记 `error`，一眼能分辨环境问题和真实缺陷。
2. **`raise_on_error=True` 要把 `error.type` 还原成异常类。**
   `InvalidPrompt` / `PromptTooLong` → `ValueError`，`TimeoutError` → `TimeoutError`，
   其余 `RuntimeError`。HTTP 层只剩字符串，不映射就跟源码版语义对不上。
3. **只转发白名单参数。** 服务端对未知参数是静默忽略的（实测传 `{"不存在的参数":1}`
   仍返回 `ok=true`），所以拼错的参数名不会报错，必须由客户端自己收紧。

## 六、错误都是 HTTP 200

实测三种错误输入全部返回 **HTTP 200**，错误在 body 的 `error` 里：

| 输入 | HTTP | `error.type` | `error.where` |
| --- | --- | --- | --- |
| `{"prompt": ""}` | 200 | `InvalidPrompt` | `input` |
| `{"prompt": "啊"*2500}` | 200 | `PromptTooLong` | `input` |
| `{}`（缺字段） | 200 | `InvalidPrompt` | `input` |

**判定失败必须读 `ok`，不能看状态码。** 超长是拒绝（不截断），`answer` 为空。

限流时是 `CloudLLMError`，`error.where` 为 `run_research_flow`，
此时 `references` 仍有内容但 `citation` 全零、`usage.context` 为 `{}`（见契约速查 §12）。

## 七、缓存

`/chat` **默认开缓存**（第二次同 prompt 返回 `cached=true`）。
`use_cache=false` 实测有效——连续两次都不命中。

批量评测一律 `use_cache=False`，`conftest._Agent` 已经统一注入，不用逐条写。
理由：缓存键不含故障注入状态，开着会让两条用例互相串结果、假通过。

## 八、排查顺序

1. C 的电脑开机了吗、四个服务起了吗（先打 `/health`）
2. 防火墙放行 8610/8600/8501/8765
3. IP 变了吗（校园网 DHCP 会换段，让 C 跑 `ipconfig` 确认）
4. 8610 返回的 answer 是空的 → 那是 MOCK 演示剧本，不是故障
5. 8600 返回 `CloudLLMError` → 云 LLM 限流，切 8610 或等一会儿
