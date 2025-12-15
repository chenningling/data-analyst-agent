# Agent 自主循环模式改造计划

## 一、改造目标

将当前的「代码驱动的多阶段提示词」模式，改造为「LLM 自主决策循环」模式。

### 核心变化

| 方面 | 当前模式 | 目标模式 |
|------|---------|---------|
| 流程控制 | 代码控制，分阶段注入提示词 | LLM 自主决策下一步 |
| user 消息 | 每个阶段注入一次 | 只有最初一条 |
| 思考过程 | 硬编码的模板文本 | LLM 真实输出 |
| 任务状态 | 代码管理任务状态 | LLM 自主验收并更新状态 |
| 消息历史 | system → user → A → user → A... | system → user → A ↔ tool... → A |

---

## 二、改造难度评估

| 文件 | 改动程度 | 说明 |
|------|---------|------|
| `backend/prompts/system_prompts.py` | 🔴 大改 | 需要重写系统提示词，合并所有阶段逻辑 |
| `backend/agent/loop.py` | 🔴 大改 | 核心循环逻辑重构 |
| `backend/agent/state.py` | 🟡 小改 | 简化阶段管理，可能删除部分字段 |
| `backend/agent/llm_client.py` | 🟢 无改动 | 保持现状 |
| `frontend/src/components/AgentProcess.tsx` | 🟡 小改 | 新增思考过程的展示样式 |
| `frontend/src/hooks/useWebSocket.ts` | 🟢 无改动 | 事件结构不变 |

**总体难度**：中等（约 1-2 天工作量）

---

## 三、详细改造方案

### 3.1 提示词改造 (`system_prompts.py`)

#### 当前结构
```
AGENT_SYSTEM_PROMPT     → 基础身份定义（短）
PLANNING_PROMPT         → 规划阶段指令
EXECUTION_PROMPT        → 执行阶段指令
REPORT_GENERATION_PROMPT → 报告阶段指令
ERROR_RECOVERY_PROMPT   → 错误恢复指令
```

#### 改造后结构
```
AUTONOMOUS_AGENT_PROMPT → 完整的自主 Agent 指令（合并所有阶段）
```

#### 新提示词设计

```python
AUTONOMOUS_AGENT_PROMPT = """你是一个专业的数据分析 Agent。你将自主完成用户的数据分析需求，无需等待进一步指示。

## 你的工作流程

你需要自主执行以下完整流程，每一步都要先输出你的思考，再执行动作：

### 阶段1：数据探索
首先调用 `read_dataset` 工具了解数据结构。

### 阶段2：任务规划
基于数据结构和用户需求，规划 3-5 个分析任务。

### 阶段3：逐个执行任务
对每个任务，调用 `run_code` 工具执行 Python 代码。
- 每次只执行一个任务
- 执行前说明你要做什么
- 执行后验收结果，确认任务是否完成

### 阶段4：生成报告
所有任务完成后，输出最终的 Markdown 分析报告。

## 输出格式要求（重要！）

**每次回复都必须包含以下两个标签**：

### 1. 思考过程标签
```
<thinking>
我当前的状态：...
我接下来要做的事：...
我选择这样做的原因：...
</thinking>
```

### 2. 任务状态标签
在每次回复中，输出当前所有任务的状态：
```
<tasks>
- [x] 数据探索（已完成）
- [x] 销售趋势分析（已完成）
- [ ] 地区对比分析（进行中）
- [ ] 生成最终报告（待开始）
</tasks>
```

规则：
- `[x]` 表示已完成的任务
- `[ ]` 表示未完成的任务
- 只有当你确认任务结果正确时，才标记为 `[x]`
- 如果代码执行失败，任务保持 `[ ]`，并在思考中说明原因

## 工具说明
- `read_dataset`: 读取数据集结构和预览
- `run_code`: 执行 Python 代码，可生成图表

## 代码编写规范
- 使用 pandas 处理数据
- 图表保存到 result.png
- 结果保存到 result.json
- 打印关键发现到 stdout

## 结束标志
当你完成最终报告输出后，在报告末尾添加：
```
---
[ANALYSIS_COMPLETE]
```

现在，请开始执行分析。
"""
```

---

### 3.2 循环逻辑改造 (`loop.py`)

#### 当前逻辑（伪代码）

```python
class AgentLoop:
    async def run(self):
        # 阶段1
        data_info = await self._explore_data()
        
        # 阶段2
        messages.append({"role": "user", "content": PLANNING_PROMPT})
        await self._plan_tasks(data_info)
        
        # 阶段3
        for task in tasks:
            messages.append({"role": "user", "content": EXECUTION_PROMPT})
            await self._execute_task(task)
        
        # 阶段4
        messages.append({"role": "user", "content": REPORT_GENERATION_PROMPT})
        await self._generate_report()
```

#### 改造后逻辑（伪代码）

```python
class AutonomousAgentLoop:
    async def run(self):
        # 初始化消息 - 只有 system 和一条 user
        messages = [
            {"role": "system", "content": AUTONOMOUS_AGENT_PROMPT},
            {"role": "user", "content": f"请分析数据集: {self.dataset_path}\n\n用户需求: {self.user_request}"}
        ]
        
        # 自主循环
        while self.iteration < MAX_ITERATIONS:
            self.iteration += 1
            
            # 调用 LLM
            response = self.llm.chat(messages, tools=TOOLS_SCHEMA)
            
            if response["type"] == "tool_call":
                # 执行工具
                tool_result = await self._execute_tool(response)
                
                # 添加 assistant 消息（工具调用）
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [...]
                })
                
                # 添加 tool 结果
                messages.append({
                    "role": "tool",
                    "tool_call_id": ...,
                    "content": tool_result
                })
                
                # 发送事件给前端
                await self._emit_tool_events(response, tool_result)
                
            elif response["type"] == "response":
                content = response["content"]
                
                # 添加 assistant 消息
                messages.append({"role": "assistant", "content": content})
                
                # 解析思考过程
                thinking = self._extract_thinking(content)
                if thinking:
                    await self.emit_event("llm_thinking", {
                        "thinking": thinking,
                        "is_real": True  # 标记这是真实的 LLM 思考
                    })
                
                # 【新增】解析任务状态并发送更新事件
                tasks = self._extract_tasks(content)
                if tasks:
                    await self.emit_event("tasks_updated", {
                        "tasks": tasks,
                        "source": "llm"  # 标记这是 LLM 自主更新的
                    })
                
                # 检查是否完成
                if "[ANALYSIS_COMPLETE]" in content:
                    self.state.final_report = self._extract_report(content)
                    break
        
        # 发送完成事件
        await self.emit_event("agent_completed", {...})
    
    def _extract_thinking(self, content: str) -> Optional[str]:
        """从 LLM 输出中提取思考过程"""
        import re
        match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL)
        return match.group(1).strip() if match else None
    
    def _extract_tasks(self, content: str) -> Optional[List[Dict]]:
        """
        从 LLM 输出中提取任务状态
        
        解析格式：
        <tasks>
        - [x] 数据探索
        - [x] 销售趋势分析
        - [ ] 地区对比分析
        </tasks>
        """
        import re
        match = re.search(r'<tasks>(.*?)</tasks>', content, re.DOTALL)
        if not match:
            return None
        
        tasks_content = match.group(1).strip()
        tasks = []
        
        # 解析每一行任务
        for i, line in enumerate(tasks_content.split('\n')):
            line = line.strip()
            if not line:
                continue
            
            # 匹配 - [x] 或 - [ ] 格式
            task_match = re.match(r'-\s*\[(x| )\]\s*(.+)', line, re.IGNORECASE)
            if task_match:
                is_completed = task_match.group(1).lower() == 'x'
                task_name = task_match.group(2).strip()
                
                # 去除可能的状态说明（如 "（已完成）"）
                task_name = re.sub(r'（.*?）', '', task_name).strip()
                
                tasks.append({
                    "id": i + 1,
                    "name": task_name,
                    "status": "completed" if is_completed else "pending"
                })
        
        return tasks if tasks else None
```

---

### 3.3 状态管理简化 (`state.py`)

#### 可删除/简化的内容

```python
# 这些在自主模式下可能不需要精细管理
class AgentPhase(str, Enum):
    # 简化为：RUNNING / COMPLETED / ERROR
    pass

# Task 的 status 管理可以简化
# 因为 LLM 自己会决定任务是否完成
```

#### 需要新增的内容

```python
@dataclass
class AgentState:
    # 新增：记录 LLM 的思考历史
    thinking_history: List[str] = field(default_factory=list)
    
    # 新增：LLM 自己规划的任务（从输出中解析）
    planned_tasks: List[str] = field(default_factory=list)
```

---

### 3.4 前端展示调整

#### 3.4.1 思考过程展示 (`AgentProcess.tsx`)

```tsx
case 'llm_thinking':
  return (
    <div className="mt-2 p-3 bg-violet-500/10 rounded-lg border border-violet-500/20">
      {/* 新增：区分真实思考 vs 系统生成 */}
      {payload.is_real && (
        <div className="text-xs text-violet-400 mb-2">💭 Agent 思考中...</div>
      )}
      <p className="text-sm text-violet-200 whitespace-pre-wrap">
        {payload.thinking as string}
      </p>
    </div>
  )
```

#### 3.4.2 任务列表动态更新 (`App.tsx` 或使用 TaskList 的组件)

当前的 `TaskList.tsx` 组件已经支持各种状态显示（pending/in_progress/completed/failed），只需要：

1. 监听 `tasks_updated` 事件
2. 更新任务列表状态

```tsx
// 处理 tasks_updated 事件
case 'tasks_updated':
  // 如果是 LLM 自主更新的任务状态
  if (payload.source === 'llm') {
    setTasks(prevTasks => {
      // 合并更新：保留原有任务信息，更新状态
      return payload.tasks.map((newTask, index) => ({
        ...prevTasks[index],  // 保留 description、type 等
        ...newTask,           // 更新 status
      }))
    })
  }
  break
```

#### 3.4.3 任务列表样式（已有，无需修改）

`TaskList.tsx` 已经实现了完整的样式：
- ✅ `completed` 状态：绿色打勾 `CheckCircle`
- ⏳ `pending` 状态：灰色空圈 `Circle`
- 🔄 `in_progress` 状态：蓝色旋转 `Loader2`
- ❌ `failed` 状态：红色叉 `XCircle`

---

## 四、消息历史对比

### 当前模式

```json
[
  {"role": "system", "content": "你是数据分析Agent...（简短）"},
  
  {"role": "user", "content": "请根据用户需求规划任务...（长）"},
  {"role": "assistant", "content": "{tasks: [...]}"},
  
  {"role": "user", "content": "请执行任务1...（长）"},
  {"role": "assistant", "tool_calls": [run_code]},
  {"role": "tool", "content": "执行结果..."},
  
  {"role": "user", "content": "请执行任务2...（长）"},
  {"role": "assistant", "tool_calls": [run_code]},
  {"role": "tool", "content": "执行结果..."},
  
  {"role": "user", "content": "请生成报告...（长）"},
  {"role": "assistant", "content": "# 分析报告..."}
]
```

### 改造后模式

```json
[
  {"role": "system", "content": "你是数据分析Agent，你将自主完成...（完整指令）"},
  
  {"role": "user", "content": "请分析: sales.csv\n需求: 分析销售趋势"},
  
  {"role": "assistant", "content": "<thinking>首先我需要了解数据结构...</thinking>\n\n<tasks>\n- [ ] 数据探索\n- [ ] 销售趋势分析\n- [ ] 地区对比\n- [ ] 生成报告\n</tasks>", "tool_calls": [read_dataset]},
  {"role": "tool", "content": "数据有10列，1000行..."},
  
  {"role": "assistant", "content": "<thinking>数据已了解，现在规划并执行第一个任务...</thinking>\n\n<tasks>\n- [x] 数据探索\n- [ ] 销售趋势分析\n- [ ] 地区对比\n- [ ] 生成报告\n</tasks>", "tool_calls": [run_code]},
  {"role": "tool", "content": "执行成功，输出..."},
  
  {"role": "assistant", "content": "<thinking>任务1完成，结果显示Q4增长15%，继续任务2...</thinking>\n\n<tasks>\n- [x] 数据探索\n- [x] 销售趋势分析\n- [ ] 地区对比\n- [ ] 生成报告\n</tasks>", "tool_calls": [run_code]},
  {"role": "tool", "content": "执行成功..."},
  
  {"role": "assistant", "content": "<thinking>所有分析任务完成，生成报告...</thinking>\n\n<tasks>\n- [x] 数据探索\n- [x] 销售趋势分析\n- [x] 地区对比\n- [x] 生成报告\n</tasks>\n\n# 分析报告\n...\n---\n[ANALYSIS_COMPLETE]"}
]
```

**前端效果**：每次 LLM 回复后，任务列表会实时更新，已完成的任务显示绿色打勾 ✅

---

## 五、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| LLM 陷入死循环 | 高 | 设置 MAX_ITERATIONS 限制 |
| LLM 跳过某些任务 | 中 | 在提示词中强调必须完成所有步骤 |
| LLM 忘记输出结束标记 | 中 | 添加迭代次数检测 + 备用结束判断 |
| 思考过程格式不规范 | 低 | 使用正则表达式容错解析 |
| Token 消耗增加 | 低 | 长期看可能减少（无重复的阶段提示词） |

---

## 六、实施步骤

### 第一阶段：提示词改造（0.5 天）

1. [ ] 设计新的 `AUTONOMOUS_AGENT_PROMPT`
   - 包含 `<thinking>` 思考过程标签
   - 包含 `<tasks>` 任务状态标签
2. [ ] 删除不再需要的分阶段提示词
3. [ ] 测试提示词效果（可用 OpenAI Playground）

### 第二阶段：循环逻辑重构（1 天）

1. [ ] 创建新的 `AutonomousAgentLoop` 类（可保留旧类做对比）
2. [ ] 实现自主循环逻辑
3. [ ] 实现思考过程解析（`_extract_thinking`）
4. [ ] 实现任务状态解析（`_extract_tasks`）
5. [ ] 实现完成检测（`[ANALYSIS_COMPLETE]`）
6. [ ] 发送 `llm_thinking` 事件（真实思考）
7. [ ] 发送 `tasks_updated` 事件（任务状态更新）

### 第三阶段：状态管理调整（0.25 天）

1. [ ] 简化 `AgentPhase` 枚举
2. [ ] 添加思考历史记录
3. [ ] 支持 LLM 自主管理的任务列表

### 第四阶段：前端适配（0.25 天）

1. [ ] 更新 `llm_thinking` 事件展示（区分真实思考 vs 系统消息）
2. [ ] 处理 `tasks_updated` 事件，动态更新任务列表
3. [ ] 确保 `TaskList.tsx` 正确显示打勾状态
4. [ ] 测试完整流程

### 第五阶段：测试与优化（0.5 天）

1. [ ] 端到端测试
2. [ ] 边界情况处理（LLM 忘记输出标签、格式错误等）
3. [ ] 性能对比（Token 消耗、响应时间）

---

## 七、回滚方案

建议保留当前的 `AgentLoop` 类，新建 `AutonomousAgentLoop` 类。通过配置切换：

```python
# config/settings.py
AGENT_MODE = "autonomous"  # 或 "staged"

# main.py
if settings.AGENT_MODE == "autonomous":
    from agent.autonomous_loop import AutonomousAgentLoop as AgentLoop
else:
    from agent.loop import AgentLoop
```

---

## 八、预期收益

1. **真实的思考过程展示**：用户可以看到 LLM 的真实推理过程
2. **动态任务状态更新**：任务列表实时打勾，直观展示进度
3. **更自然的对话流**：消息历史更符合对话逻辑，无"假用户"消息
4. **代码简化**：删除分阶段的复杂逻辑
5. **更好的可扩展性**：添加新能力只需修改提示词
6. **增强用户体验**：用户能清晰看到 Agent 在"想什么"和"做到哪了"

---

## 九、文件清单

| 文件路径 | 操作 | 备注 |
|---------|------|------|
| `backend/prompts/system_prompts.py` | 修改 | 新增 AUTONOMOUS_AGENT_PROMPT（含 thinking 和 tasks 标签） |
| `backend/agent/autonomous_loop.py` | 新建 | 自主循环实现 + 标签解析逻辑 |
| `backend/agent/loop.py` | 保留 | 作为回滚方案 |
| `backend/agent/state.py` | 修改 | 简化阶段管理，支持 LLM 自主任务 |
| `backend/main.py` | 修改 | 支持模式切换 |
| `frontend/src/components/AgentProcess.tsx` | 修改 | 更新思考展示，处理 tasks_updated 事件 |
| `frontend/src/components/TaskList.tsx` | 无需修改 | 已支持各状态显示 |
| `frontend/src/App.tsx` | 小改 | 处理 tasks_updated 事件更新状态 |

---

## 十、LLM 输出示例

```
<thinking>
我刚完成了销售趋势分析任务。从结果来看：
- Q4 销售额增长了 15%
- 电子产品类目表现最好
- 华东地区贡献了 40% 的销售额

接下来我要进行地区对比分析，重点关注各地区的销售差异。
</thinking>

<tasks>
- [x] 数据探索
- [x] 销售趋势分析
- [ ] 地区对比分析
- [ ] 生成最终报告
</tasks>

我现在执行地区对比分析...
```

**前端展示效果**：
- 🧠 思考过程：显示紫色高亮的思考内容
- ✅ 任务列表：「数据探索」和「销售趋势分析」打勾变绿，其余保持灰色

---

*文档创建时间：2024-12-15*
*预计工作量：1.5 - 2 天*


