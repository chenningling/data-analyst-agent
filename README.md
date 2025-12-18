# 数据分析 Agent 🤖📊

基于大模型的自动化数据分析工具，支持上传 Excel/CSV 数据，通过 AI Agent 自动规划和执行分析任务，生成带可视化的复盘报告。

> **📚 项目说明**：这是一个学习项目，在探索不同 Agent 架构模式的过程中，迭代了多个版本的循环实现。因此项目中包含了 5 种不同的 Agent 运行模式，每种模式代表了不同的设计思路和实现方式，便于学习和对比。

## 🎬 项目演示

### 演示视频

https://github.com/user-attachments/assets/1e3afc0b-32d9-4c13-a59f-c77ed540dd3e

## ✨ 功能特点

- **智能分析规划**：AI 自动理解需求并规划分析步骤
- **自动代码生成**：根据任务自动生成 Python 分析代码
- **实时进度展示**：WebSocket 实时推送执行过程，支持任务状态实时更新
- **多种运行模式**：支持 5 种不同的 Agent 运行模式，适应不同场景
- **丰富的可视化**：支持 ECharts 交互图表、Mermaid 流程图、matplotlib 图表
- **专业报告生成**：自动生成 Markdown 格式的分析报告，包含图表和洞察
- **任务管理**：支持任务列表展示、进度跟踪、错误处理
- **会话管理**：支持停止分析、会话日志记录、事件缓冲

## 🏗️ 项目结构

```
date_analyst1.0/
├── backend/                    # 后端服务
│   ├── main.py                # FastAPI 主入口（API 路由、WebSocket）
│   ├── agent/                 # Agent 核心模块
│   │   ├── __init__.py        # Agent 模块导出
│   │   ├── loop.py            # 传统分阶段模式（AgentLoop）
│   │   ├── autonomous_loop.py # 自主模式（AutonomousAgentLoop）
│   │   ├── hybrid_loop.py     # 混合模式（HybridAgentLoop）
│   │   ├── task_driven_loop.py # 任务驱动模式（TaskDrivenAgentLoop）
│   │   ├── tool_driven_loop.py # 工具驱动模式（ToolDrivenAgentLoop，推荐）
│   │   ├── state.py           # 状态管理（AgentState, Task, TaskStatus）
│   │   └── llm_client.py      # LLM 客户端封装
│   ├── tools/                 # 工具模块
│   │   ├── read_dataset.py    # 数据读取工具（支持 Excel/CSV）
│   │   └── run_code.py        # 代码执行工具（安全子进程执行）
│   ├── prompts/               # 提示词模板
│   │   └── system_prompts.py  # 系统提示词定义
│   ├── config/                # 配置模块
│   │   └── settings.py        # 配置管理（Pydantic Settings）
│   ├── utils/                 # 工具函数
│   │   └── logger.py          # 日志记录（包含 SessionLogger）
│   ├── requirements.txt       # Python 依赖
│   └── venv/                  # Python 虚拟环境
├── frontend/                  # 前端应用
│   ├── src/
│   │   ├── App.tsx            # 主应用组件
│   │   ├── components/        # React 组件
│   │   │   ├── AgentProcess.tsx  # Agent 执行过程展示
│   │   │   ├── TaskList.tsx      # 任务列表组件
│   │   │   ├── FileUpload.tsx    # 文件上传组件
│   │   │   ├── ReportViewer.tsx  # 报告查看器
│   │   │   ├── CodeBlock.tsx     # 代码块组件
│   │   │   └── ui/               # UI 基础组件
│   │   ├── hooks/             # 自定义 Hooks
│   │   │   └── useWebSocket.ts   # WebSocket 连接管理
│   │   └── lib/               # 工具函数
│   │       └── utils.ts          # 通用工具函数
│   ├── package.json           # Node.js 依赖
│   ├── vite.config.ts         # Vite 配置
│   └── tailwind.config.js     # Tailwind CSS 配置
├── example/                   # 示例代码
│   └── kimi_thinking.py       # 示例脚本
├── plan/                      # 计划文档
│   ├── autonomous_loop_refactoring.md
│   └── tool_driven_architecture.md
├── record/                    # 会话日志记录
│   └── [session logs]         # 自动生成的会话日志
└── README.md                  # 项目文档
```

## 🚀 快速开始

### 环境要求

- Python 3.9+
- Node.js 18+
- OpenAI API Key（或兼容的 API）

### 1. 配置环境变量

创建 `backend/.env` 文件：

```env
# LLM 配置
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，默认使用 OpenAI
# 推荐使用带思考能力的模型，可以获得更好的推理和分析质量
LLM_MODEL=kimi-k2-thinking-turbo           # 推荐：带思考能力的模型（如 kimi-k2-thinking-turbo）
# 其他可选模型：gpt-4o, gpt-4-turbo, claude-3-opus 等

# Agent 配置
AGENT_MODE=tool_driven                      # 运行模式：tool_driven, task_driven, hybrid, autonomous, staged
MAX_ITERATIONS=25                            # 最大迭代次数
CODE_TIMEOUT=30                              # 代码执行超时时间（秒）
MAX_ITERATIONS_PER_TASK=5                    # 每个任务最大迭代次数（仅 hybrid 模式）

# 文件配置
UPLOAD_DIR=/tmp/data_analyst_uploads        # 上传文件存储目录
MAX_FILE_SIZE=52428800                       # 最大文件大小（字节，默认 50MB）

# WebSocket 配置
WS_HEARTBEAT_INTERVAL=30                     # WebSocket 心跳间隔（秒）
```

**模型选择建议**：
- **强烈推荐使用带思考能力的模型**（如 `kimi-k2-thinking-turbo`）
  - 思考能力模型能够进行更深入的推理和分析
  - 在复杂的数据分析任务中表现更优
  - 能够更好地理解数据结构和分析需求
  - 生成的分析代码质量更高，错误更少
- 如果使用其他模型，建议使用 `gpt-4o` 或 `gpt-4-turbo` 等高性能模型

**Agent 运行模式说明**：
- `tool_driven`（推荐）：LLM 完全自主管理任务生命周期，通过工具调用管理任务
- `task_driven`：代码驱动 + 工具辅助，代码控制任务流程
- `hybrid`：混合模式，代码控制任务流程 + LLM 自主执行
- `autonomous`：自主模式，LLM 完全自主决策（使用标签解析）
- `staged`：传统分阶段模式，明确的阶段划分

### 2. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn main:app --reload --port 8003
```

### 3. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 4. 访问应用

打开浏览器访问 `http://localhost:3000`

## 📖 使用指南

### 基本使用流程

1. **上传数据**：支持 Excel (.xlsx, .xls) 和 CSV 格式
   - 文件大小限制：默认 50MB
   - Excel 文件支持多 Sheet，默认读取第一个 Sheet

2. **输入需求**：描述您想要分析的内容，越详细越好，例如：
   - "分析销售趋势并找出异常值"
   - "统计各产品类别的销售占比，并生成饼图"
   - "预测下个季度的销售额，使用时间序列分析"
   - "对比不同地区的销售表现，找出最佳和最差地区"

3. **开始分析**：点击"开始分析"按钮
   - 系统会创建会话并返回 session_id
   - 前端自动建立 WebSocket 连接接收实时事件

4. **查看进度**：
   - **任务列表**：左侧显示任务规划列表和状态
   - **执行过程**：右侧显示 Agent 执行过程，包括：
     - LLM 思考过程
     - 工具调用记录
     - 代码执行结果
     - 生成的图表

5. **查看报告**：分析完成后自动切换到报告 Tab
   - 报告为 Markdown 格式
   - 包含数据洞察、图表、结论和建议

### 高级功能

- **停止分析**：在分析过程中可以点击"停止分析"按钮
- **任务详情**：点击任务列表中的任务查看详细执行过程
- **连接状态**：顶部显示 WebSocket 连接状态

### API 端点

#### REST API

- `POST /api/start`：启动分析任务
  - 参数：`file` (文件), `user_request` (字符串)
  - 返回：`session_id`, `ws_url`

- `POST /api/stop/{session_id}`：停止分析任务

- `POST /api/start-sync`：同步方式启动分析（等待完成后返回结果）

- `GET /api/health`：健康检查

#### WebSocket

- `WS /ws/{session_id}`：连接到特定会话，接收实时事件
- `WS /ws`：广播连接，接收所有会话的事件

### 事件类型

Agent 会通过 WebSocket 推送以下事件：

- `connected`：WebSocket 连接成功
- `agent_started`：Agent 开始执行
- `data_explored`：数据探索完成
- `tasks_planned`：任务规划完成
- `tasks_updated`：任务状态更新
- `task_started`：任务开始执行
- `task_completed`：任务执行完成
- `task_failed`：任务执行失败
- `image_generated`：图表生成完成
- `report_generated`：报告生成完成
- `agent_completed`：Agent 执行完成
- `agent_error`：Agent 执行出错
- `agent_stopped`：Agent 被停止
- `llm_thinking`：LLM 思考过程（流式输出）
- `tool_call`：工具调用
- `tool_result`：工具执行结果

## 🛠️ 技术架构

### 后端技术栈

- **FastAPI**：高性能异步 Web 框架
- **WebSocket**：实时双向通信，支持事件推送和心跳
- **OpenAI API**：大模型能力（支持兼容 OpenAI API 的其他服务）
- **Pydantic Settings**：配置管理，支持环境变量和类型验证
- **Pandas**：数据处理和分析
- **Matplotlib/Seaborn**：数据可视化
- **Subprocess**：安全代码执行（子进程隔离）

### 前端技术栈

- **React 18**：UI 框架，使用 Hooks 和函数组件
- **TypeScript**：类型安全，提升开发体验
- **Vite**：快速构建工具，支持 HMR
- **Tailwind CSS**：原子化 CSS 框架
- **ECharts**：交互式图表库（通过 echarts-for-react）
- **Mermaid**：流程图和图表渲染
- **React Markdown**：Markdown 渲染，支持代码高亮
- **Lucide React**：图标库

### 架构特点

- **前后端分离**：前端通过 REST API 和 WebSocket 与后端通信
- **事件驱动**：使用 WebSocket 实时推送执行事件
- **会话管理**：每个分析任务有独立的 session_id
- **事件缓冲**：解决 WebSocket 连接时序问题，确保不丢失事件
- **日志记录**：自动记录会话日志到 `record/` 目录
- **错误处理**：完善的错误处理和恢复机制

## 🔧 Agent 工作原理

### 整体流程

```
用户上传数据 → LLM 解析结构 → 规划任务
→ 代码生成 → run_code → 结果回传
→ 下一步任务 → 直至所有任务完成
→ 生成最终复盘报告（含图表）
```

### Agent 运行模式详解

> **💡 学习说明**：本项目是学习项目，在探索 Agent 架构设计的过程中，迭代实现了 5 种不同的运行模式。每种模式代表了不同的设计思路：
> - **Staged 模式**：最初的传统分阶段实现
> - **Autonomous 模式**：尝试让 LLM 完全自主决策
> - **Task-Driven 模式**：代码控制 + 工具辅助的平衡方案
> - **Hybrid 模式**：混合控制策略的探索
> - **Tool-Driven 模式**：最终推荐的完全工具化方案
> 
> 这些版本的迭代过程帮助深入理解不同架构模式的优缺点，以及在不同场景下的适用性。

项目支持 5 种不同的 Agent 运行模式，每种模式有不同的控制策略：

#### 1. Tool-Driven 模式（推荐）⭐

**特点**：LLM 完全自主管理任务生命周期

- **控制权**：LLM 通过工具调用完全自主管理
- **任务管理**：通过 `todo_write` 工具创建、更新任务状态
- **适用场景**：需要最大灵活性的复杂分析任务
- **优势**：LLM 可以动态调整任务，适应复杂场景

#### 2. Task-Driven 模式

**特点**：代码驱动 + 工具辅助

- **控制权**：代码控制任务流程，工具辅助执行
- **任务管理**：代码维护任务列表，逐个执行
- **适用场景**：需要严格任务顺序的场景
- **优势**：执行流程可控，易于调试

#### 3. Hybrid 模式

**特点**：代码控制任务流程 + LLM 自主执行

- **控制权**：代码控制任务选择，LLM 自主执行每个任务
- **任务管理**：代码维护任务列表，LLM 执行任务内容
- **适用场景**：需要任务顺序控制但执行灵活的场景
- **优势**：平衡了控制性和灵活性

#### 4. Autonomous 模式

**特点**：LLM 完全自主决策（标签解析）

- **控制权**：LLM 通过标签（`<thinking>`, `<tasks>`）自主决策
- **任务管理**：LLM 在回复中维护任务状态标签
- **适用场景**：需要 LLM 完全自主的场景
- **优势**：LLM 可以灵活调整计划

#### 5. Staged 模式（传统）

**特点**：传统的明确阶段划分

- **控制权**：代码明确划分阶段
- **任务管理**：分阶段执行：数据探索 → 任务规划 → 执行 → 报告
- **适用场景**：简单直接的分析任务
- **优势**：流程清晰，易于理解

### 核心工具

Agent 使用以下工具完成分析任务：

1. **`read_dataset`**：读取数据集，返回数据结构、统计信息和预览
2. **`run_code`**：在安全子进程中执行 Python 代码，支持数据处理和可视化
3. **`todo_write`**（仅 tool_driven 模式）：管理任务清单，创建、更新任务状态

### 核心循环流程

1. **数据探索**：调用 `read_dataset` 了解数据结构
2. **任务规划**：LLM 根据需求规划分析任务
3. **任务执行**：逐个执行任务，调用 `run_code` 生成代码并执行
4. **结果评估**：评估执行结果，决定下一步
5. **报告生成**：所有任务完成后生成最终 Markdown 报告

## ⚠️ 注意事项

### 安全提示

- 当前版本为 **Demo 级别**，非生产环境
- 代码执行在子进程中运行，但建议在隔离环境使用（如 Docker 容器）
- 代码执行有超时限制（默认 30 秒），防止无限循环
- 建议文件大小不超过 50MB，大文件可能导致内存问题

### 使用建议

- **API Key 安全**：不要将 API Key 提交到版本控制系统
- **数据隐私**：上传的数据会临时存储在服务器，注意数据隐私
- **资源限制**：长时间运行的分析任务可能消耗较多 API 调用
- **错误处理**：如果分析失败，检查日志文件（`record/` 目录）获取详细信息

### 性能优化

- **强烈推荐使用带思考能力的模型**（如 `kimi-k2-thinking-turbo`）
  - 思考能力模型能够进行更深入的推理，生成更高质量的分析代码
  - 在复杂的数据分析任务中，思考过程有助于理解数据结构和业务逻辑
  - 能够减少代码执行错误，提高分析成功率
- 如果使用其他模型，建议使用 `gpt-4o` 或 `gpt-4-turbo` 等高性能模型
- 对于简单任务，可以使用 `staged` 模式减少 API 调用
- 对于复杂任务，推荐使用 `tool_driven` 模式获得更好的灵活性

## 🔍 调试与日志

### 日志文件

- 会话日志自动保存到 `record/` 目录
- 日志文件命名格式：`session_{session_id}_{timestamp}.txt`
- LLM 交互日志：`llm_log_{session_id}_{timestamp}.txt`

### 查看日志

```bash
# 查看最新的会话日志
ls -lt record/ | head -5

# 查看特定会话的日志
cat record/session_*.txt | grep "session_id"
```

### 常见问题

1. **WebSocket 连接失败**：检查后端是否启动，端口是否正确（8003）
2. **文件上传失败**：检查文件格式和大小限制
3. **代码执行超时**：检查代码是否有无限循环，或增加 `CODE_TIMEOUT` 配置
4. **任务执行失败**：查看执行过程的错误信息，Agent 会尝试自动修复

## 📝 开发计划

- [x] 支持多种 Agent 运行模式
- [x] WebSocket 实时通信
- [x] 任务管理和状态跟踪
- [x] 会话日志记录
- [ ] 支持更多数据格式（JSON, Parquet 等）
- [ ] 添加更多分析工具（统计分析、机器学习等）
- [ ] 优化错误恢复机制
- [ ] 支持多轮对话和需求调整
- [ ] 添加分析历史记录和结果缓存
- [ ] 支持自定义分析模板
- [ ] 添加数据导出功能

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 License

MIT License

