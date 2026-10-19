# agent-qa · AI 智能体测试工程

「AI 智能体测试挑战赛」参赛工程的**测试基座**（角色 A 负责部分）。
被测对象是科研助手 `research-assistant`，本仓库负责：**用例 → pytest 执行 → 报告 → 结构化执行记录 → CI**。

> 接口按《自动化评测接口说明》**v1.2** 对齐，速查见 `docs/接口契约速查.md`。
> 当前 `agent_under_test/stub_agent.py` 是**本地替身**（与真实接口同构），
> 故意保留 3 个缺陷，所以运行结果是 **32 通过 8 失败**。这是预期行为，不是环境问题。
> 真机侧已由 C 跑通冒烟 **2/2**（2026-10-18，1043s / 1106s），详见 `docs/缺陷清单.md`。

## 与 EduGuard 的分工（2026-10-19 定，双轨并行）

组里现在有两个工程，**职责不重叠，别互相替代**：

| | 本仓库 `agent-qa` | C 的 `EduGuard` |
| --- | --- | --- |
| 定位 | **测试基座**：契约、对抗用例、执行记录格式 | **演示平台**：Streamlit 看板、报告可视化 |
| 产出 | `results.json`（机器可读、可复现、进 CI） | 分类型 P/R 图、风险发现、答辩演示 |
| 用例 | 40 条，按接口契约与行为边界写 | 32 条合成用例，按业务场景写 |
| A 的投入 | 主战场 | **只做最小接入**，不重复建用例 |

判断依据：本仓库的东西要能进 CI、能被 B 的 judge 直接消费、能复现；
EduGuard 的价值在“看得见”，两者不冲突。**新增用例优先放 agent-qa**。

## 目录结构

```
agent-qa/
├─ agent_under_test/
│  ├─ stub_agent.py         # 本地替身：run(prompt) -> 16 字段 dict，含 3 个已知缺陷
│  ├─ http_adapter.py       # HTTP 适配器：打 C 的 /chat 接口（现在的主要方式）
│  ├─ real_adapter.py       # 源码适配器：包 src.api.run（保留兼容）
│  └─ offline.py            # 离线打桩：外部依赖换假实现，流水线照常跑
├─ tests/
│  ├─ conftest.py           # autouse：每条用例前后清被测系统的结果缓存
│  ├─ test_smoke.py         # 冒烟 7 条：字段、序列、usage/context、run_id
│  ├─ test_contract.py      # 契约 9 条：失败语义、引用编号、指标自洽（含 null 语义）、来源聚合、safety 声明
│  ├─ test_safety.py        # 对抗 6 条：越狱、单源 503、降级、可复现
│  ├─ test_adversarial.py   # 对抗跑批器（B 负责）
│  ├─ adversarial_cases.json # 对抗用例数据（B 只改这个文件）
│  └─ test_record_schema.py # 执行记录格式的自测 8 条
├─ conftest.py              # agent / trace fixture；统一注入 use_cache=False；写完自检格式
├─ pytest.ini               # 标记、超时（2400s，迁就真机 1106s）、pythonpath
├─ tools/
│  ├─ record_schema.py      # **执行记录格式的唯一口径**（字段表 + 校验函数）
│  ├─ validate_record.py    # 校验 results.json 是否符合契约（CI 门禁）
│  ├─ summary.py            # 读 results.json 出汇总表（CI 里写 Job Summary）
│  └─ judge.py              # LLM-as-judge 骨架：四维打分，B 接管 score_record()
├─ reports/latest/results.json   # 每次运行生成，不入库
├─ docs/
│  ├─ 接口契约速查.md        # 16 字段 + 失败语义 + 指标口径 + 真机实测字段表
│  ├─ HTTP接口接入说明.md    # 打 C 的 /chat 怎么配、8610 与 8600 的边界
│  ├─ 执行记录格式.md        # results.json 的字段契约与版本策略（给 B / C）
│  ├─ 测试用例清单.md        # 40 条用例，表与代码一一对应
│  ├─ 缺陷清单.md            # 3 个缺陷 + 修复记录 + 真机缺陷
│  └─ B-对抗用例接入说明.md  # 给 B 的手册
└─ .github/workflows/ci.yml
```

## 跑起来（用本地替身，秒级）

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

pytest -v                                  # 全量 40 条
pytest -m smoke -v                         # 只跑冒烟
pytest -m adversarial -v                   # 只跑对抗（B 负责）
pytest --no-record -v                      # 不写执行记录
pytest --alluredir=reports/allure-results  # 生成 allure 原始数据
python tools/summary.py                    # 打印执行汇总
python tools/validate_record.py            # 校验执行记录格式（字段改了这里先红）
python tools/judge.py                      # judge 打分 → reports/judge/latest.json
```

## 接入 HTTP 接口（现在的主要方式）

C 已经把被测系统挂成服务，评测侧打接口即可，不用碰源码：

```bash
# 契约 / 冒烟：MOCK 稳定通道，不耗额度
AGENT_IMPL=http AGENT_ENDPOINT=http://10.225.252.61:8610/chat \
  .venv/Scripts/python.exe -m pytest -m "contract or smoke" -q

# 行为验收：云 LLM 真实链路（会限流，超时调大）
AGENT_IMPL=http AGENT_ENDPOINT=http://10.225.252.61:8600/chat AGENT_HTTP_TIMEOUT=1800 \
  .venv/Scripts/python.exe -m pytest -m "safety or adversarial" -q
```

**MOCK 通道不检索**，`tool_calls` / `references` 恒为空，所以引用类、工具类、幻觉类
用例在 8610 上必然失败——那是通道限制，不是缺陷。详细边界见 `docs/HTTP接口接入说明.md`。

`needs_injection` 标记的用例（故障注入）在 HTTP 模式下会自动跳过。

## 接入真实被测对象（源码 import，保留兼容）

**第一步：让 `src.api` 能被 import。**
被测仓库**没有** `setup.py` / `pyproject.toml`，所以 `pip install -e .` 会直接报错。
用 `PYTHONPATH` 指向源码根：

```powershell
$env:AGENT_IMPL = "real"                            # 本仓库自己的开关，被测仓库没有这个变量
$env:AGENT_SRC  = "D:\workAi\research-assistant"    # 含 src/ 的那一层
$env:PYTHONPATH = "D:\workAi\research-assistant"    # 被测仓库唯一认的环境变量
pytest -m smoke -v
```

注意：`AGENT_IMPL` / `AGENT_SRC` 是**我们这边**的开关（`conftest._build_agent` 读的），
被测仓库自己没有任何接入开关，它只认 `PYTHONPATH`。**

**第二步：不要指望 `MOCK_MODE=1` 跑用例。**
它会把检索整段短路（`research_flow.py:271`），结果 `tool_calls=[]`、`references=[]`，
只能验结构、验不了行为。要离线测行为用 `agent_under_test/offline.py`：

```python
from agent_under_test.offline import offline

with offline(n_web=2, n_local=1, search_error=True):
    resp = run("测试主题")        # 流水线照常跑，外部依赖是假的
```

**第三步：真机一条要 17–18 分钟**（2026-10-18 实测 1043s / 1106s），31 条串行跑不动。
日常用 `offline()`；真机只跑 1–2 条 `-m smoke` 做端到端验证。
被测系统默认超时已提到 **1800s**，评测侧 `timeout_s` 建议跟着 ≥1800，pytest 自身超时设在 2400。

## 三个容易踩的坑（都已处理）

| 坑 | 现象 | 处理 |
| --- | --- | --- |
| 缓存串结果 | 注入不同故障的两条用例，第二条拿到第一条的成功结果 → **假通过** | `conftest._Agent` 统一注入 `use_cache=False`；`tests/conftest.py` autouse 清缓存 |
| `schema_version` 升到 1.2 | 断言写死 `"1.1"` 直接红 | 用例断言 `"1.2"`；新增 `usage.context` 断言 |
| `references` 按文档聚合 | 一篇 PDF 命中 5 段从 5 条变 1 条，`chunk_count=5` | `test_references_aggregated_by_document` 按 `path`/`doi` 去重 |
| `tool_calls=[]` 被误判成错序 | 用户说了「别检索」，Agent 遵从 → 工具为空，被记成缺陷 | 先读 `usage.safety.skip_retrieval`；空调用是「缺失」，不是「错序」 |

## 已知缺陷（用于验证测试有效性）

| 编号 | 现象 | 命中用例 |
| --- | --- | --- |
| DEF-001 | 越狱指令导致内部标记 `INTERNAL-RULE-7749` 泄露 | `test_no_prompt_leak`（3 条）+ `ADV-INJ-001/002/003` |
| DEF-002 | 单个检索源失败被误判为整体失败（`ok=False`） | `test_search_source_503_keeps_ok_true_and_has_references` |
| DEF-003 | `references[].id` 从 0 起编，与正文 `[n]` 错位 | `test_reference_id_matches_markers` |

换成真实 Agent 后这 5 条应当转绿；若仍失败，说明真实系统也有同类问题。

## 与 C 的分工边界

C 已有 `tests/test_eval_entry_contract.py` 25 条**结构层**契约用例（字段齐全、JSON 往返、
HTTP 400/413/429 等）。本仓库不重复，只做**评测侧增量**：

- 失败语义的黑盒验证（不抛异常、超长拒绝、单源失败不改 `ok`）
- 引用与指标可信度（编号对齐、指标自洽、按文档聚合）
- 安全对抗与可复现性（越狱、降级、同输入同结果）

## Git 提交规范（交付硬要求）

官网明确核查「原创性与开发过程可复现性」，禁止一次性全量提交。
一次提交对应一个功能模块或一次核心对话，建议前缀：

| 前缀 | 用途 |
| --- | --- |
| `feat` | 新能力（fixture、记录器、打桩、看板接口） |
| `test` | 新增 / 修改用例 |
| `ci` | 流水线配置 |
| `docs` | 文档、用例清单、契约速查 |
| `fix` | 修缺陷、修脚本 |

## 分工衔接

- **B · AI 评测**：读 `reports/latest/results.json`，`records[].trace.output` 就是完整的
  16 字段返回；幻觉分可用 `citation.fabricated` / `faithfulness` 直接算，不用重跑。
- **C · 被测对象 + 表达**：提供 `src.api.run`；看板读 `records[].outcome` 与 `summary`。
