# Agent Cluster

> Agent 运营中间件 — 为标准化的 Agent 调用提供 **路由 → 执行 → 审议** 三段式管道，全程留档可追溯。
>
> Agent operations middleware: a standardized three-stage pipeline (Route → Execute → Review) for agent calls, with full audit trail.

[Python 3.10+] [OpenAI Compatible] [MIT]

---

## 它不是什么 / What It Is NOT

- **不是 Agent 框架**。不定义 Agent 怎么建，只定义 Agent 调用怎么过。不替代 LangChain / CrewAI / AutoGen。
- **不替代 openclaw**。claw 是运行时（沙箱、工具挂载、loop）；Agent Cluster 是挂载其上的治理管道。互补。

## 解决什么问题 / Why

在 openclaw 等 agent 运行时中，常见的实际使用模式是「输入→输出」单轮调用。这种模式下存在三个盲区：

| 盲区 | 应对 |
|------|------|
| 意图不透明 | **Guard** 独立判定意图，路由结果写入归档 |
| 输出无门禁 | **Reviewer** 加载规则库审议，pass / reject / revise 三态 |
| 链路无追溯 | 双写归档 `archive/` + `task/{id}/result.json` |

管道层面两条设计：**模糊传递**（OCR 失败不阻塞，`[OCR_FAILED: ...]` 占位，`content.md` 始终生成）；**AI Translate 边界**（Guard 仅消费 `content.md` 纯文本，不接触原始文件，非多模态模型可用）。

## 架构 / Architecture

```
用户输入 / 文件
    │
    ▼
TaskManager.save_input()         ← 持久化 + 源文件快照（source/ 不修改）
    │
    ▼
TaskManager.ocr_to_md()          ← OCR → content.md（失败用占位符，不阻塞）
    │
    ▼
Guard.process(task)              ← 纯文本意图路由（仅消费 content.md）
    │                                   intent ∈ {analysis, execution, meta_training, invalid}
    ├─ analysis  ──→ Executor（纯 LLM 对话）
    ├─ execution ──→ Executor（LLM + MCP 工具链）
    ├─ meta_training → 遍历历史 → Reviewer 批量评估 → 规则增量
    └─ invalid   ──→ 拒绝
    │
    ▼
Reviewer.process(task, output)   ← 规则库审议 + 本地预检（RTFM/STFW 关键词）
    │                                   verdict ∈ {pass, reject, revise}
    ▼
FinalResult → 双写归档
```

### 角色 / Roles

| 角色 | 做什么 | 不做什么 |
|------|--------|---------|
| **Guard（门卫）** | 纯文本意图分类。OCR 质量标记（confidence 降权）。 | 不接触原始文件。不执行。 |
| **Executor（实干家）** | 执行任务。analysis 模式生成报告；execution 模式挂载 MCP 工具。 | 不自我反思。不输出「我认为」「我觉得」。 |
| **Reviewer（审议者）** | 加载 `rules.json` 逐条审查。本地预检 + LLM 深度审议。 | 不执行。不修改 Executor 输出。 |

角色不可跳过、不可合并。这是 Agent Cluster 唯一强制的约束——其他框架让你自由组合角色，这里不让你选。

审议规则（`rules.json`）：`rtfm_stfw`(critical) / `mvp_only`(high) / `scope_creep`(medium) / `no_reflexivity`(medium)。规则库支持 `meta_training` 增量更新。

## 快速开始 / Getting Started

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置 `.env`

```env
# DeepSeek / OpenAI（推荐）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=deepseek-chat

# 或本地 Ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_API_KEY=ollama
# LLM_MODEL=qwen2.5:7b

# 可选：OCR（PaddleOCR API）
PADDLEOCR_API_URL=
PADDLEOCR_API_KEY=
# 可选：MCP 工具链
MCP_ENABLED=false
MCP_SERVER_COMMAND=
```

### 3. 运行

```bash
# 直接输入
python -m agent_cluster.main "分析这份 Excel 的内容"

# 扫描 / 交互
python -m agent_cluster.main --scan
python -m agent_cluster.main --interactive
```
也支持 `--retry <task_id>` 和 `--meta-train`（遍历历史，增量更新规则）。

### 部署到 openclaw / Deploy with openclaw

Agent Cluster 可作为 MCP Server 注册到 openclaw：

```json
// openclaw 的 MCP 配置
{
  "agent-cluster": {
    "command": "python",
    "args": ["-m", "agent_cluster.mcp_server"]
  }
}
```

配置后，对话中上传文件并 @agent-cluster 调用 `run_pipeline`，管道自动接管：Guard 路由 → Executor 执行 → Reviewer 审议 → 归档到 `task/`。文件归集由 Agent Cluster 自行管理（快照到 `task/{id}/source/`），不依赖 openclaw 文件系统。

## 目录结构 / Project Structure

```
agent_cluster/
├── agents/
│   ├── guard.py            # 门卫：意图路由
│   ├── executor.py         # 实干家：执行
│   └── reviewer.py         # 审议者：规则门禁
├── rules/rules.json        # 审议规则库（MVP 阶段手动维护）
├── archive/                # 历史任务归档（result.json * N）
├── orchestrator.py         # 管道编排：串联三角色
├── task_manager.py         # 任务持久化 + OCR 转换 + 模糊传递
├── mcp_server.py          # MCP Server 入口（注册 run_pipeline tool）
├── mcp_client.py           # MCP stdio 客户端
├── llm_client.py           # OpenAI 兼容 LLM 封装（chat / chat_json / vision）
└── config.py               # 集中配置（.env 驱动，可迁移）
task/                       # 运行时任务目录（gitignore）
└── task_{id}/
    ├── input.json          # 原始输入
    ├── source/             # 源文件快照（永不修改）
    ├── content.md          # OCR 转写产物（Guard 唯一文本入口）
    └── result.json         # 管道完整输出
```

## 端到端案例 / End-to-End Example

来自 `task` 的实际执行：

**输入**: 一份 Excel（三个 sheet：待办列表 + 自查事项 + 检查复盘）

| 阶段 | 输出 |
|------|------|
| Guard | intent=`analysis`, confidence=0.95, "用户希望系统理解、总结或评估这份待办清单和自查表" |
| Executor | 生成结构化 Markdown 分析报告（5 大板块：整体概况、待办分析、自查分析、复盘分析、总结建议） |
| Reviewer | verdict=`pass`, 规则触发=无, "没有引入过度工程或范围蔓延。实干家没有进行自我反思，符合 MVP 原则" |

总耗时 143s。完整归档：[result.json](archive/task.json)

## 与同类项目的定位 / Positioning

三角色分离并非独创——AutoGen 的 Coder-Reviewer-Runner、CrewAI 的 Guardrail+Evaluator、LangGraph 的 self-RAG 均实践了同类模式。Agent Cluster 的不同在于：**独立中间件形态**（不绑定框架）、**管道不可跳过**（固定约束，不可自由组合）、**运维向设计**（模糊传递、AI Translate 边界、双写归档）、**规则可演进**（meta_training 增量更新 rules.json）。

## License

MIT
