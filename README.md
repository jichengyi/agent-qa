# agent-qa · AI 智能体测试工程

「AI 智能体测试挑战赛」参赛工程的**测试基座**（角色 A 负责部分）。
被测对象是一个科研助手 Agent，本仓库负责：**用例 → pytest 执行 → 报告 → 结构化执行记录 → CI**。

> 当前 `agent_under_test/stub_agent.py` 是**占位被测对象**，为了让整条链路先跑通。
> 它故意保留了 3 个缺陷，其中 DEF-002 已修复；现在运行结果是 **10 通过 4 失败**
> （DEF-001 命中 1 条、DEF-003 命中 3 条参数化用例）。这是预期行为，不是环境问题。

## 目录结构

```
agent-qa/
├─ agent_under_test/        # 被测对象（接真实 Agent 后只留客户端封装）
│  └─ stub_agent.py         # 占位实现，含 3 个已知缺陷
├─ tests/
│  ├─ test_smoke.py         # 冒烟：可用性、时延、工具链顺序
│  ├─ test_contract.py      # 契约：空输入、引用字段、引用来源可信
│  └─ test_safety.py        # 对抗：越狱泄露、超长输入、多轮一致性
├─ conftest.py              # agent / trace fixture + 执行记录落盘
├─ pytest.ini               # 标记、超时、pythonpath
├─ tools/summary.py         # 读 results.json 出汇总表（CI 里写 Job Summary）
├─ reports/latest/results.json   # 每次运行生成，不入库
├─ docs/
│  ├─ 测试用例清单.md
│  └─ 缺陷清单.md
└─ .github/workflows/ci.yml
```

## 跑起来

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

pytest -v                                  # 全量
pytest -m smoke -v                         # 只跑冒烟
pytest -m "not slow" -v                    # 跳过慢用例
pytest --no-record -v                      # 不写执行记录
pytest --alluredir=reports/allure-results  # 生成 allure 原始数据
allure serve reports/allure-results        # 本地看报告（需装 allure 命令行）
python tools/summary.py                    # 打印执行汇总
```

## 已知缺陷（用于验证测试有效性）

| 编号 | 现象 | 命中用例 |
| --- | --- | --- |
| DEF-001 | 空主题不报错，仍编造回答与引用 | `test_empty_topic_should_raise` |
| DEF-002 | ~~超长输入直接抛 `RuntimeError`，未降级~~ **已修复**：截断至 2000 字并提示 | `test_overlong_input_graceful` |
| DEF-003 | 越狱指令导致系统提示词泄露 | `test_no_system_prompt_leak` |

换成真实被测 Agent 后，DEF-001 与 DEF-003 这 4 条应当转绿；若仍失败，说明真实 Agent 也存在同类问题。
届时可以把 CI 里的 `continue-on-error: true` 去掉，让失败直接卡住流水线。

## 接入真实被测 Agent

只改 `conftest.py` 的 `agent` fixture：

```python
@pytest.fixture(scope="session")
def agent():
    from agent_under_test.client import HttpAgentClient
    return HttpAgentClient(base_url=os.environ["AGENT_BASE_URL"])
```

**保持 `answer()` 的返回结构不变**：

```python
{
    "trace_id": "…",
    "answer": "回答正文",
    "citations": [{"title": "…", "url": "https://…", "year": 2024}],
    "tool_calls": [{"tool": "search", "args": {...}}],
    "elapsed_ms": 123.4,
}
```

B 的 judge 直接读 `reports/latest/results.json` 里的 `records[].trace.output`，
C 的看板读 `records[].outcome` 与 `summary`，接口不要随意改。

## Git 提交规范（交付硬要求）

官网明确核查「原创性与开发过程可复现性」，禁止一次性全量提交。
一次提交对应一个功能模块或一次核心对话，建议前缀：

| 前缀 | 用途 |
| --- | --- |
| `feat` | 新能力（fixture、记录器、看板接口） |
| `test` | 新增 / 修改用例 |
| `ci` | 流水线配置 |
| `docs` | 文档、用例清单 |
| `fix` | 修缺陷、修脚本 |

## 分工衔接

- **B · AI 评测**：消费 `results.json` 的 `trace` 字段做 judge 打分；对抗用例放进 `tests/test_adversarial_*.py`，打 `@pytest.mark.adversarial`。
- **C · 被测对象 + 表达**：负责替换 `agent_under_test`、做 Streamlit 看板（读 `results.json`）、录视频。
