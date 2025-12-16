# 工具驱动架构改造计划（方案 B）

## 一、背景与问题

### 当前架构的问题

在 `task_driven_loop.py` 中，虽然引入了 `todo_write` 工具，但其作用被"稀释"了：

| 问题点 | 说明 |
|-------|------|
| 任务选择权被代码拿走 | `for task in pending_tasks` 由代码层遍历 |
| 开始状态由代码设置 | `state.update_task_status(task.id, IN_PROGRESS)` |
| 结束条件由代码判断 | `_check_completion_condition()` 函数 |
| "关闭清单"动作消失 | 代码层直接触发 `_phase_reporting()` |

### `todo_write` 工具的完整语义

参考 Cursor 的 todo_write 工具设计：
```
通过调用 todo_write 工具，并传入以下参数：
- todos: 任务对象数组（id, content, status）
- merge: 是否为增量更新

工具应支持完整的任务生命周期：
1. 创建任务清单（merge=false）
2. 更新任务状态（merge=true）
3. 所有任务完成后，关闭清单并给出总结
```

---

## 二、两种架构对比

### 方案 A：代码驱动 + 工具辅助（当前架构）

```
┌─────────────────────────────────────────────────────────────┐
│                    代码层作为"指挥官"                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  代码层: for task in pending_tasks:                         │
│    │                                                        │
│    ├─① 代码层设置 status = in_progress                      │
│    ├─② 代码层注入任务上下文 → LLM                           │
│    ├─③ LLM 调用 run_code 执行                              │
│    ├─④ LLM 调用 todo_write(completed) 验收                 │
│    ├─⑤ 代码层检查状态，决定继续/重试                        │
│    └─⑥ 代码层判断结束条件                                   │
│                                                             │
│  代码层: 进入报告阶段 → LLM 生成报告                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘

todo_write 的作用：仅用于"状态标记"（相当于打勾 ✓）
```

### 方案 B：完全工具驱动（LLM 自主管理）

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM 作为"指挥官"                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  LLM 自主循环:                                              │
│    │                                                        │
│    ├─① LLM 检查当前任务清单状态                             │
│    ├─② LLM 自主选择下一个要执行的任务                       │
│    ├─③ LLM 调用 todo_write(in_progress) 标记开始           │
│    ├─④ LLM 调用 run_code 执行任务                          │
│    ├─⑤ LLM 调用 todo_write(completed) 标记完成             │
│    ├─⑥ LLM 自主判断：还有未完成任务？继续循环               │
│    └─⑦ LLM 判断全部完成 → 输出最终报告                      │
│                                                             │
│  代码层: 只负责执行工具 + 安全兜底                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘

todo_write 的作用：完整的任务生命周期管理（创建→开始→完成→关闭）
```

---

## 三、核心差异分析

| 维度 | 方案A（代码驱动） | 方案B（LLM驱动） |
|------|------------------|-----------------|
| **控制权** | 代码层 | LLM |
| **任务顺序** | 代码层按列表顺序执行 | LLM 自主选择 |
| **结束判断** | `_check_completion_condition()` | LLM 判断"所有任务完成" |
| **上下文注入** | 每次代码层注入当前任务 | LLM 自己记住进度 |
| **todo_write 调用时机** | 仅验收时 | 开始、完成、关闭 |
| **报告生成** | 代码层触发 `_phase_reporting()` | LLM 自主决定何时输出 |
| **代码复杂度** | 较高（多阶段控制逻辑） | 极简（只有工具执行） |

---

## 四、方案 B 详细设计

### 4.1 代码层职责（极简化）

```python
class ToolDrivenAgentLoop:
    """完全工具驱动的 Agent（代码层只做兜底）"""
    
    async def run(self):
        # 1. 初始化：只发一条消息
        initial_prompt = self._build_initial_prompt()
        self.messages.append({"role": "user", "content": initial_prompt})
        
        # 2. 简单的自主循环
        while self.iteration < self.max_iterations:
            response = self.llm.chat(self.messages, tools=TOOLS)
            
            if response["type"] == "tool_call":
                # 执行工具，返回结果
                await self._handle_tool_call(response)
            else:
                # LLM 输出文本（可能是最终报告）
                content = response["content"]
                self.messages.append({"role": "assistant", "content": content})
                
                # 检查是否完成
                if self._is_complete(content):
                    self.final_report = content
                    break
        
        # 3. 发送完成事件
        await self.emit_event("agent_completed", {...})
```

### 4.2 代码层移除的逻辑

```python
# ❌ 移除：分阶段控制
# - _phase_planning()
# - _phase_execution()  
# - _phase_reporting()

# ❌ 移除：任务循环控制
# - for task in pending_tasks
# - _execute_single_task()

# ❌ 移除：结束条件判断
# - _check_completion_condition()

# ❌ 移除：代码层状态更新
# - state.update_task_status(task.id, IN_PROGRESS)
```

### 4.3 代码层保留的逻辑

```python
# ✅ 保留：安全边界
# - 最大迭代数限制（防止死循环）
# - 超时控制
# - 错误兜底

# ✅ 保留：工具执行
# - _handle_tool_call() - 执行 read_dataset, run_code, todo_write

# ✅ 保留：事件推送
# - emit_event() - 推送进度给前端
```

### 4.4 提示词设计

```python
TOOL_DRIVEN_SYSTEM_PROMPT = """你是一个专业的数据分析 Agent，通过工具自主完成数据分析任务。

## 可用工具

1. `read_dataset` - 读取数据结构
2. `run_code` - 执行 Python 代码
3. `todo_write` - 管理任务清单（核心工具）

## todo_write 工具使用指南

### 创建任务清单（分析开始时）
```json
{
  "todos": [
    {"id": "1", "content": "探索数据结构", "status": "pending"},
    {"id": "2", "content": "分析销售趋势", "status": "pending"},
    {"id": "3", "content": "生成可视化图表", "status": "pending"}
  ],
  "merge": false
}
```

### 开始执行任务
```json
{
  "todos": [{"id": "1", "content": "探索数据结构", "status": "in_progress"}],
  "merge": true
}
```

### 完成任务
```json
{
  "todos": [{"id": "1", "content": "探索数据结构", "status": "completed"}],
  "merge": true
}
```

## 工作流程

1. 调用 `read_dataset` 了解数据
2. 调用 `todo_write` 创建任务清单（3-5个任务）
3. 对于每个任务：
   - 调用 `todo_write` 标记为 in_progress
   - 调用 `run_code` 执行分析
   - 调用 `todo_write` 标记为 completed
4. 所有任务完成后，直接输出 Markdown 格式的分析报告
5. 报告末尾添加 `[ANALYSIS_COMPLETE]` 标记

## 重要规则

- 你完全自主决定任务执行顺序
- 每个任务开始前必须调用 todo_write 标记 in_progress
- 每个任务完成后必须调用 todo_write 标记 completed
- 所有任务完成后才能输出最终报告
"""
```

---

## 五、优劣评估

### 方案 B 的优势

| 优势 | 说明 |
|------|------|
| **架构简洁** | 代码层只有约 100 行，移除大量控制逻辑 |
| **工具语义完整** | `todo_write` 发挥完整作用（创建→开始→完成→关闭） |
| **灵活性高** | LLM 可根据情况调整执行顺序 |
| **真正的 Agent** | 符合 Agent 的设计理念（自主决策） |
| **日志清晰** | 所有状态变化都有工具调用记录 |

### 方案 B 的风险

| 风险 | 应对措施 |
|------|---------|
| LLM 忘记调用 todo_write | 在提示词中强调 + 代码层可选兜底 |
| LLM 跳过某些任务 | 提示词强调"必须完成所有任务" |
| LLM 陷入死循环 | 最大迭代数限制 |
| API 调用增加 | 每个任务增加 2 次 todo_write 调用 |
| 上下文消耗增加 | LLM 需要记住任务进度（可通过工具返回值缓解） |

---

## 六、实施计划

### 阶段 1：创建新模块（0.5 天）
1. [x] 创建 `tool_driven_loop.py`
2. [x] 实现简化的自主循环逻辑
3. [x] 设计新的系统提示词

### 阶段 2：更新配置（0.25 天）
1. [x] 添加 `tool_driven` 模式到 settings.py
2. [x] 更新 main.py 支持新模式
3. [x] 更新 `__init__.py` 导出

### 阶段 3：测试验证（0.25 天）
1. [ ] 端到端测试
2. [ ] 验证 todo_write 调用次数和时机
3. [ ] 验证最终报告质量

---

## 七、与原有模式的关系

```
backend/agent/
├── loop.py                 # 原始分阶段模式（staged）
├── autonomous_loop.py      # 自主循环模式（标签解析）
├── hybrid_loop.py          # 混合模式（代码控制+LLM执行）
├── task_driven_loop.py     # 任务驱动模式（代码驱动+工具辅助）
└── tool_driven_loop.py     # 🆕 工具驱动模式（LLM完全自主）
```

配置切换：
```bash
# .env
AGENT_MODE=tool_driven  # 新增选项
```

---

## 八、预期效果

### LLM 调用日志预期

```
# 1. 读取数据
LLM → read_dataset

# 2. 创建任务清单
LLM → todo_write (创建 3 个 pending 任务, merge=false)

# 3. 任务 1
LLM → todo_write (id=1, status=in_progress, merge=true)
LLM → run_code (执行分析)
LLM → todo_write (id=1, status=completed, merge=true)

# 4. 任务 2
LLM → todo_write (id=2, status=in_progress, merge=true)
LLM → run_code (执行分析)
LLM → todo_write (id=2, status=completed, merge=true)

# 5. 任务 3
LLM → todo_write (id=3, status=in_progress, merge=true)
LLM → run_code (执行分析)
LLM → todo_write (id=3, status=completed, merge=true)

# 6. 输出报告
LLM → 文本输出（最终 Markdown 报告 + [ANALYSIS_COMPLETE]）
```

---

*文档创建时间：2024-12-16*
*作者：Agent 开发助手*

