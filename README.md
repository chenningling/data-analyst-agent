# 数据分析 Agent 🤖📊

基于大模型的自动化数据分析工具，支持上传 Excel/CSV 数据，通过 AI Agent 自动规划和执行分析任务，生成带可视化的复盘报告。

## ✨ 功能特点

- **智能分析规划**：AI 自动理解需求并规划分析步骤
- **自动代码生成**：根据任务自动生成 Python 分析代码
- **实时进度展示**：WebSocket 实时推送执行过程
- **丰富的可视化**：支持 ECharts 交互图表、Mermaid 流程图、matplotlib 图表
- **专业报告生成**：自动生成 Markdown 格式的分析报告

## 🏗️ 项目结构

```
date_analyst1.0/
├── backend/                 # 后端服务
│   ├── main.py             # FastAPI 主入口
│   ├── agent/              # Agent 核心模块
│   │   ├── loop.py         # Agent 主循环
│   │   ├── state.py        # 状态管理
│   │   └── llm_client.py   # LLM 客户端
│   ├── tools/              # 工具模块
│   │   ├── read_dataset.py # 数据读取工具
│   │   └── run_code.py     # 代码执行工具
│   ├── prompts/            # 提示词模板
│   ├── config/             # 配置模块
│   └── utils/              # 工具函数
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── components/     # React 组件
│   │   ├── hooks/          # 自定义 Hooks
│   │   └── lib/            # 工具函数
│   └── ...
└── README.md
```

## 🚀 快速开始

### 环境要求

- Python 3.9+
- Node.js 18+
- OpenAI API Key（或兼容的 API）

### 1. 配置环境变量

创建 `backend/.env` 文件：

```env
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

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

1. **上传数据**：支持 Excel (.xlsx, .xls) 和 CSV 格式
2. **输入需求**：描述您想要分析的内容，例如：
   - "分析销售趋势并找出异常"
   - "统计各产品类别的销售占比"
   - "预测下个季度的销售额"
3. **等待分析**：Agent 会自动规划任务并执行
4. **查看报告**：分析完成后会生成包含图表的报告

## 🛠️ 技术架构

### 后端

- **FastAPI**：高性能 Web 框架
- **WebSocket**：实时通信
- **OpenAI API**：大模型能力
- **Pandas**：数据处理
- **Matplotlib/Seaborn**：数据可视化

### 前端

- **React 18**：UI 框架
- **TypeScript**：类型安全
- **Tailwind CSS**：样式框架
- **ECharts**：交互式图表
- **Mermaid**：流程图渲染

## 🔧 Agent 工作原理

```
用户上传数据 → LLM 解析结构 → 规划任务
→ 代码生成 → run_code → 结果回传
→ 下一步任务 → 直至所有任务完成
→ 生成最终复盘报告（含图表）
```

### 核心循环（Agent Loop）

1. **Planning**：LLM 根据需求生成任务清单
2. **Execution**：逐个执行任务，调用工具
3. **Self-evaluation**：评估结果，决定下一步

## ⚠️ 注意事项

- 当前版本为 **Demo 级别**，非生产环境
- 代码执行在子进程中运行，但建议在隔离环境使用
- 建议文件大小不超过 50MB

## 📝 开发计划

- [ ] 支持更多数据格式
- [ ] 添加更多分析工具
- [ ] 优化错误恢复机制
- [ ] 支持多轮对话
- [ ] 添加分析历史记录

## 📄 License

MIT License

