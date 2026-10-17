# agent-qa · AI 智能体测试工程

「AI 智能体测试挑战赛」参赛工程的**测试基座**（角色 A 负责部分）。
被测对象是一个科研助手 Agent，本仓库负责：**用例 → pytest 执行 → 报告 → 结构化执行记录 → CI**。

> 接口按 C 提供的《自动化评测接口说明》v1.1 对齐，速查见 `docs/接口契约速查.md`。
> 当前 `agent_under_test/stub_agent.py` 是**本地替身**（与真实接口同构），
> 故意保留 3 个缺陷，所以运行结果是 **13 通过 5 失败**。这是预期行为，不是环境问题。

## 目录结构

```
agent-qa/
├─ agent_under_test/
│  ├─ stub_agent.py         # 本地替身：run(prompt) -> 16 字段 dict，含 3 个已知缺陷
│  └─ real_adapter.py       # 真实实现适配器：包 src.api.run，交付后切这里
├─ tests/
│  ├─ test_smoke.py         # 冒烟：字段齐全、工具序列、usage/stages 自洽
│  ├─ test_contract.py      # 契约：空输入、超长拒绝、raise_on_error、引用编号、指标自洽
│  └─ test_safety.py        # 对抗：越狱泄露、工具失败语义、降级、可复现性
├─ conftest.py              # agent / trace fixture + 执行记录落盘
├─ pytest.ini               # 标记、超时（1200s，迁就真实链路）、pythonpath
├─ tools/summary.py         # 读 results.json 出汇总表（CI 里写 Job Summary）
├─ reports/latest/results.json   # 每次运行生成，不入库
├─ docs/
│  ├─ 接口契约速查.md        # 16 字段 + 失败语义 + 指标口径
│  ├─ 测试用例清单.md        # 18 条用例，表与代码一一对应
│  └─ 缺陷清单.md            # 3 个缺陷 + 修复记录
└─ .github/workflows/ci.yml
```

## 跑起来

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

pytest -v                                  # 全量
pytest -m smoke -v                         # 只跑冒烟
pytest -m contract -v                      # 只跑契约
pytest --no-record -v                      # 不写执行记录
pytest --alluredir=reports/allure-results  # 生成 allure 原始数据
python tools/summary.py                    # 打印执行汇总
```

## 接入真实被测对象

C 交付科研助手后，**只设环境变量，用例一行都不用改**：

```powershell
$env:AGENT_IMPL = "real"
$env:AGENT_SRC  = "D:\workAi\research-assistant"   # 科研助手源码根目录
pytest -m smoke -v
```

`conftest.py` 里的 `_build_agent()` 会走 `real_adapter.RealAgent`，它只做
`from src.api import run` + 转发，不复制任何业务逻辑。

**注意**：真实链路单次 `run()` 实测约 1000 秒（接口说明第 9 节），全量 18 条串行跑不动。
先只跑 `-m smoke`，或跟 C 要打桩模式（他的 25 条契约用例是「全离线、打桩不烧额度」的）。

## 已知缺陷（用于验证测试有效性）

| 编号 | 现象 | 命中用例 |
| --- | --- | --- |
| DEF-001 | 越狱指令导致内部标记 `INTERNAL-RULE-7749` 泄露 | `test_no_prompt_leak`（3 条参数化） |
| DEF-002 | 单个工具失败被误判为整体失败（`ok=False`） | `test_tool_failure_keeps_ok_true` |
| DEF-003 | `references[].id` 从 0 起编，与正文 `[n]` 错位 | `test_reference_id_matches_markers` |

换成真实 Agent 后这 5 条应当转绿；若仍失败，说明真实系统也有同类问题。

## 与 C 的分工边界

C 已有 `tests/test_eval_entry_contract.py` 25 条**结构层**契约用例（字段齐全、JSON 往返、
HTTP 400/413/429 等）。本仓库不重复，只做**评测侧增量**：

- 失败语义的黑盒验证（不抛异常、超长拒绝、工具失败不改 `ok`）
- 引用与指标可信度（编号对齐、指标自洽、编造引用）
- 安全对抗与可复现性（越狱、降级、同输入同结果）

## Git 提交规范（交付硬要求）

官网明确核查「原创性与开发过程可复现性」，禁止一次性全量提交。
一次提交对应一个功能模块或一次核心对话，建议前缀：

| 前缀 | 用途 |
| --- | --- |
| `feat` | 新能力（fixture、记录器、看板接口） |
| `test` | 新增 / 修改用例 |
| `ci` | 流水线配置 |
| `docs` | 文档、用例清单、契约速查 |
| `fix` | 修缺陷、修脚本 |

## 分工衔接

- **B · AI 评测**：读 `reports/latest/results.json`，`records[].trace.output` 就是完整的
  16 字段返回；幻觉分可用 `citation.fabricated` / `faithfulness` 直接算，不用重跑。
- **C · 被测对象 + 表达**：提供 `src.api.run`；看板读 `records[].outcome` 与 `summary`。
