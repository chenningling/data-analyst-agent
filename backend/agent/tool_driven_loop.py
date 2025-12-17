"""
工具驱动自主循环 Agent 模块（方案 B）

核心理念：LLM 完全自主管理任务生命周期
- 代码层只负责：工具执行 + 安全兜底
- LLM 负责：任务规划 + 任务选择 + 状态更新 + 完成判断 + 报告生成

todo_write 工具的完整作用：
1. 创建任务清单（merge=false）
2. 标记任务开始（status=in_progress, merge=true）
3. 标记任务完成（status=completed, merge=true）
4. LLM 自主判断所有任务完成后输出报告
"""
import json
import uuid
import time
from typing import Callable, Dict, Any, Optional, List, Awaitable
from datetime import datetime

from agent.state import AgentState, AgentPhase, Task, TaskStatus
from agent.llm_client import get_llm_client
from tools import tool_read_dataset, tool_run_code
from config.settings import settings
from utils.logger import logger


# ============================================================
# 工具 Schema
# ============================================================

TOOL_DRIVEN_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_dataset",
            "description": "读取数据集，返回数据结构、统计信息和预览。分析开始时首先调用此工具了解数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "preview_rows": {
                        "type": "integer",
                        "description": "预览行数，默认5",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": "执行 Python 代码进行数据分析。使用 pandas 处理数据，matplotlib 绑图，图表保存到 result.png。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码"
                    },
                    "description": {
                        "type": "string",
                        "description": "代码功能描述"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": """管理分析任务清单。这是核心任务管理工具，用于：
1. 创建任务清单（分析开始时，merge=false）
2. 标记任务开始（status=in_progress，merge=true）
3. 标记任务完成（status=completed，merge=true）

每个任务在执行前必须标记为 in_progress，完成后必须标记为 completed。""",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "任务对象数组",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "任务唯一标识（如 '1', '2', '3'）"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "任务内容（动词开头，简洁明确）"
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                                    "description": "任务状态"
                                }
                            },
                            "required": ["id", "content", "status"]
                        }
                    },
                    "merge": {
                        "type": "boolean",
                        "description": "true=增量更新（只更新指定任务），false=完全覆盖（创建新清单）"
                    }
                },
                "required": ["todos", "merge"]
            }
        }
    }
]


# ============================================================
# 系统提示词
# ============================================================

TOOL_DRIVEN_SYSTEM_PROMPT = """你是一个专业的数据分析 Agent，通过工具自主完成数据分析任务。

## 可用工具

1. **read_dataset** - 读取数据结构和预览
2. **run_code** - 执行 Python 代码进行分析
3. **todo_write** - 任务状态同步工具（核心工具）

## 核心原则：通过工具调用实现任务闭环

`todo_write` 是任务状态同步工具，你必须通过它来：
- **规划**：创建任务清单
- **执行**：标记任务开始（in_progress）
- **验收**：标记任务完成（completed）

**关键**：每完成一个任务，都必须调用 `todo_write` 将其标记为 completed。这不仅是状态更新，更是对该任务结果的**验收确认**。只有当所有任务都被标记为 completed，整个分析才算完成。

## todo_write 工具使用指南

### 1. 创建任务清单（分析开始时）
根据用户需求和数据特点，调用 todo_write 创建任务清单：
```json
{{
  "todos": [
    {{"id": "1", "content": "探索数据基本特征", "status": "pending"}},
    {{"id": "2", "content": "分析销售趋势", "status": "pending"}},
    {{"id": "3", "content": "生成可视化图表", "status": "pending"}},
    {{"id": "4", "content": "总结分析并输出报告", "status": "pending"}}
  ],
  "merge": false
}}
```

### 2. 开始执行任务
执行任务前，先标记为 in_progress：
```json
{{
  "todos": [{{"id": "1", "content": "探索数据基本特征", "status": "in_progress"}}],
  "merge": true
}}
```

### 3. 完成任务（验收）
任务执行成功后，**必须调用 todo_write 标记为 completed**：
```json
{{
  "todos": [{{"id": "1", "content": "探索数据基本特征", "status": "completed"}}],
  "merge": true
}}
```
这一步是对任务结果的**验收确认**，表示你确认该任务已正确完成。

## 完整工作流程

1. **了解数据**：调用 `read_dataset` 读取数据结构
2. **创建任务清单**：调用 `todo_write`（merge=false）根据用户需求创建任务
3. **逐个执行任务**（循环执行，直到所有任务完成）：
   - 调用 `todo_write` 标记任务为 in_progress（开始）
   - 执行任务（调用 run_code 或输出分析内容）
   - **调用 `todo_write` 标记任务为 completed（验收）**
4. **完成闭环**：当所有任务都被标记为 completed 时，分析完成

## 代码编写规范

```python
import pandas as pd
import matplotlib.pyplot as plt
import os

# 读取数据
df = pd.read_csv(os.environ['DATASET_PATH'])  # 或 pd.read_excel(...)

# 中文支持
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 分析代码...

# 保存图表
plt.savefig('result.png', dpi=150, bbox_inches='tight')
plt.close()

# 打印关键结果
print("分析结果：...")
```

## ⚠️ 关键规则（必须严格遵守）

1. **每个任务都必须经过完整的状态流转**：
   - pending → in_progress → completed
   - 每次状态变化都必须调用 todo_write

2. **验收是通过工具调用实现的**：
   - 调用 todo_write 标记 completed = 验收该任务通过
   - 不调用工具就输出内容 ≠ 任务完成

3. **最后一个任务也必须调用工具验收**：
   - 即使已经输出了总结报告
   - 仍然必须调用 todo_write 将最后一个任务标记为 completed
   - 这是整个分析的**最终验收**

4. **任务闭环判断**：
   - 只有当所有任务都是 completed 状态时，分析才算真正完成
   - 在此之前，即使输出了报告内容，也不会交付给用户

## 报告格式要求

```markdown
# 数据分析报告

## 📊 数据概览
...

## 🔍 关键发现
...

## 📈 分析详情
...

## 💡 洞察与建议
...

## 📋 总结
...
```

## 错误示例（禁止这样做）

❌ 执行完代码后不调用 todo_write，直接进入下一个任务
❌ 输出报告后不调用 todo_write 验收最后一个任务
❌ 跳过某个任务的状态更新

## 正确示例

✅ 每个任务执行后，立即调用 todo_write 标记为 completed
✅ 最后一个任务（输出报告）完成后，也调用 todo_write 标记为 completed
✅ 所有任务都是 completed 后，分析才算完成
"""


class ToolDrivenAgentLoop:
    """
    工具驱动自主循环 Agent
    
    核心理念：LLM 完全自主，代码层只做兜底
    """
    
    def __init__(
        self,
        dataset_path: str,
        user_request: str,
        event_callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        self.dataset_path = dataset_path
        self.user_request = user_request
        self.event_callback = event_callback
        self.start_time = None
        
        # Agent 状态
        self.state = AgentState(
            session_id=str(uuid.uuid4()),
            dataset_path=dataset_path,
            user_request=user_request
        )
        
        # 验收标志：由 agent 通过工具调用设置
        self.report_validated = False
        self.pending_report = None  # 暂存报告内容，等待验收
        
        # 获取 LLM 客户端并设置 session（每个 session 独立日志文件）
        self.llm = get_llm_client()
        self.llm.set_session(self.state.session_id)
        
        # 初始化消息历史
        self.state.messages = [
            {"role": "system", "content": TOOL_DRIVEN_SYSTEM_PROMPT}
        ]
        
        # 配置
        self.max_iterations = settings.MAX_ITERATIONS
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"[ToolDrivenAgent] 初始化")
        logger.info(f"[ToolDrivenAgent] Session: {self.state.session_id}")
        logger.info(f"[ToolDrivenAgent] 数据集: {dataset_path}")
        logger.info(f"[ToolDrivenAgent] 用户需求: {user_request[:100]}...")
        logger.info(f"[ToolDrivenAgent] 模式: 完全工具驱动（LLM 自主管理）")
        logger.info(f"{'#'*60}\n")
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """发送事件到前端"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.state.session_id,
            "payload": payload
        }
        logger.info(f"[ToolDrivenAgent] 发送事件: {event_type}")
        await self.event_callback(event)
    
    # ============================================================
    # 主运行循环（极简）
    # ============================================================
    
    async def run(self) -> Dict[str, Any]:
        """
        运行工具驱动循环（流式版本）
        
        核心逻辑：只发一条消息，让 LLM 自主完成所有工作
        支持实时流式输出，让前端能看到 Agent 的思考过程
        """
        self.start_time = time.time()
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[ToolDrivenAgent] ===== 开始执行（流式模式）=====")
        logger.info(f"[ToolDrivenAgent] 最大迭代数: {self.max_iterations}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request,
                "mode": "tool_driven_streaming"
            })
            
            # 只发一条初始消息，让 LLM 自主执行
            initial_prompt = self._build_initial_prompt()
            self.state.messages.append({"role": "user", "content": initial_prompt})
            
            await self.emit_event("phase_change", {"phase": "autonomous_running"})
            self.state.phase = AgentPhase.EXECUTING
            
            # 简单的自主循环
            while self.state.iteration < self.max_iterations:
                self.state.iteration += 1
                
                logger.info(f"\n[ToolDrivenAgent] ----- 迭代 {self.state.iteration}/{self.max_iterations} -----")
                
                iteration_start = time.time()
                
                # 通知前端开始新的 LLM 调用
                await self.emit_event("llm_start", {
                    "iteration": self.state.iteration,
                    "message": f"开始第 {self.state.iteration} 次思考..."
                })
                
                # 流式内容缓冲
                streaming_content = ""
                streaming_reasoning = ""
                last_emit_time = time.time()
                
                # 流式回调：内容块
                async def on_content_chunk(chunk: str):
                    nonlocal streaming_content, last_emit_time
                    streaming_content += chunk
                    
                    # 每隔 100ms 或累积 50 字符发送一次，避免过于频繁
                    current_time = time.time()
                    if current_time - last_emit_time > 0.1 or len(chunk) > 50:
                        await self.emit_event("llm_streaming", {
                            "content": chunk,
                            "full_content": streaming_content,
                            "iteration": self.state.iteration,
                            "type": "content"
                        })
                        last_emit_time = current_time
                
                # 流式回调：思考过程
                async def on_reasoning_chunk(chunk: str):
                    nonlocal streaming_reasoning, last_emit_time
                    streaming_reasoning += chunk
                    
                    current_time = time.time()
                    if current_time - last_emit_time > 0.1 or len(chunk) > 50:
                        await self.emit_event("llm_streaming", {
                            "content": chunk,
                            "full_content": streaming_reasoning,
                            "iteration": self.state.iteration,
                            "type": "reasoning"
                        })
                        last_emit_time = current_time
                
                # 流式回调：工具调用开始
                async def on_tool_call_start(tool_name: str):
                    await self.emit_event("llm_tool_calling", {
                        "tool": tool_name,
                        "iteration": self.state.iteration,
                        "message": f"准备调用工具: {tool_name}"
                    })
                
                # 使用流式 API 调用 LLM
                response = await self.llm.chat_stream(
                    self.state.messages,
                    tools=TOOL_DRIVEN_TOOLS_SCHEMA,
                    on_content_chunk=on_content_chunk,
                    on_reasoning_chunk=on_reasoning_chunk,
                    on_tool_call_start=on_tool_call_start
                )
                
                iteration_duration = time.time() - iteration_start
                
                # 通知前端 LLM 调用完成
                await self.emit_event("llm_complete", {
                    "iteration": self.state.iteration,
                    "duration": iteration_duration,
                    "type": response["type"]
                })
                
                if response["type"] == "error":
                    logger.error(f"[ToolDrivenAgent] LLM 调用失败: {response['error']}")
                    raise Exception(f"LLM 调用失败: {response['error']}")
                
                if response["type"] == "tool_call":
                    # 执行工具
                    await self._handle_tool_call(response, iteration_duration)
                    
                else:
                    # LLM 输出文本（可能是报告内容）
                    content = response["content"]
                    reasoning = response.get("reasoning")
                    
                    # 将 reasoning 拼接到 content 中，保持上下文连贯性
                    assistant_content = content if content else ""
                    if reasoning:
                        if assistant_content:
                            assistant_content = f"[思考：{reasoning[:500]}...]\n\n{assistant_content}" if len(reasoning) > 500 else f"[思考：{reasoning}]\n\n{assistant_content}"
                        else:
                            assistant_content = f"[思考：{reasoning[:500]}...]" if len(reasoning) > 500 else f"[思考：{reasoning}]"
                    
                    self.state.messages.append({"role": "assistant", "content": assistant_content if assistant_content else content})
                    
                    # 发送最终的思考过程（如果流式中没有发送完整）
                    if reasoning and reasoning != streaming_reasoning:
                        await self.emit_event("llm_thinking", {
                            "thinking": reasoning,  # 不截断，发送完整内容
                            "is_real": True,
                            "is_reasoning": True,
                            "iteration": self.state.iteration,
                            "duration": iteration_duration
                        })
                        logger.info(f"[ToolDrivenAgent] 🧠 模型思考: {reasoning[:200]}...")
                    
                    # 暂存可能是报告的内容
                    if self._looks_like_report(content):
                        self.pending_report = content
                        logger.info(f"[ToolDrivenAgent] 📝 检测到报告内容，等待 agent 验收...")
                    
                    # 注意：这里不直接结束，而是继续循环让 agent 调用 todo_write 进行验收
                
                # 在工具调用后检查是否验收通过
                if self._is_complete():
                    logger.info(f"[ToolDrivenAgent] ✅ Agent 验收通过，分析完成")
                    # 使用暂存的报告或最后的内容
                    if self.pending_report:
                        self.state.final_report = self._extract_report(self.pending_report)
                    else:
                        # 查找最后一个包含报告内容的 assistant 消息
                        self.state.final_report = self._find_report_in_messages()
                    break
            
            # 完成
            self.state.phase = AgentPhase.COMPLETED
            self.state.completed_at = datetime.utcnow()
            total_time = time.time() - self.start_time
            
            logger.info(f"\n{'*'*60}")
            logger.info(f"[ToolDrivenAgent] ===== 执行完成 =====")
            logger.info(f"[ToolDrivenAgent] 总耗时: {total_time:.2f}秒")
            logger.info(f"[ToolDrivenAgent] 总迭代次数: {self.state.iteration}")
            logger.info(f"[ToolDrivenAgent] 图表数: {len(self.state.images)}")
            logger.info(f"{'*'*60}\n")
            
            # 发送报告事件
            if self.state.final_report:
                await self.emit_event("report_generated", {
                    "report": self.state.final_report
                })
            
            await self.emit_event("agent_completed", {
                "final_report": self.state.final_report,
                "images": self.state.images,
                "tasks_summary": self.state.get_tasks_summary(),
                "iterations": self.state.iteration,
                "duration": total_time
            })
            
            return {
                "status": "success",
                "session_id": self.state.session_id,
                "report": self.state.final_report,
                "images": self.state.images
            }
            
        except Exception as e:
            self.state.phase = AgentPhase.ERROR
            self.state.error = str(e)
            total_time = time.time() - self.start_time if self.start_time else 0
            
            logger.error(f"\n{'!'*60}")
            logger.error(f"[ToolDrivenAgent] 执行失败: {e}")
            logger.error(f"{'!'*60}\n", exc_info=True)
            
            await self.emit_event("agent_error", {
                "error": str(e),
                "phase": self.state.phase.value
            })
            
            return {
                "status": "error",
                "error": str(e),
                "session_id": self.state.session_id
            }
    
    def _build_initial_prompt(self) -> str:
        """构建初始提示"""
        return f"""请分析以下数据集：

## 数据文件路径
{self.dataset_path}

## 用户分析需求
{self.user_request}

## 执行步骤
1. 首先调用 `read_dataset` 了解数据结构
2. 然后调用 `todo_write` 创建任务清单（merge=false）
3. 逐个执行任务，每个任务执行前后都要更新状态
4. 所有任务完成后，输出最终分析报告

请开始执行。"""
    
    def _is_complete(self) -> bool:
        """
        检查分析是否完成
        
        核心原则：通过工具调用验收来判断完成，而非文本标记
        只有当 agent 通过 todo_write 将所有任务（特别是"验收"任务）标记为 completed 时才算完成
        """
        # 必须通过工具验收
        if not self.report_validated:
            return False
        
        # 检查任务状态
        incomplete_tasks = self._get_incomplete_tasks()
        if incomplete_tasks:
            logger.warning(f"[ToolDrivenAgent] ⚠️ 验收标记已设置，但有 {len(incomplete_tasks)} 个任务未完成:")
            for task in incomplete_tasks:
                logger.warning(f"[ToolDrivenAgent]   - [{task.id}] {task.name}: {task.status.value}")
            return False
        
        logger.info(f"[ToolDrivenAgent] ✅ Agent 自主验收通过，所有 {len(self.state.tasks)} 个任务都已完成")
        return True
    
    def _get_incomplete_tasks(self) -> List:
        """获取未完成的任务列表"""
        from agent.state import TaskStatus
        return [
            task for task in self.state.tasks 
            if task.status not in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]
        ]
    
    def _looks_like_report(self, content: str) -> bool:
        """
        检查内容是否看起来像是分析报告
        
        通过特征匹配来识别报告内容
        """
        if not content or len(content) < 200:
            return False
        
        # 报告特征关键词
        report_indicators = [
            "# 数据分析报告",
            "## 数据概览",
            "## 关键发现",
            "## 分析",
            "📊",
            "🔍",
            "📈",
            "💡"
        ]
        
        indicator_count = sum(1 for indicator in report_indicators if indicator in content)
        
        # 如果包含 2 个以上的报告特征，认为是报告
        return indicator_count >= 2
    
    def _find_report_in_messages(self) -> str:
        """
        在消息历史中查找报告内容
        
        从后往前查找，找到最后一个看起来像报告的 assistant 消息
        """
        for message in reversed(self.state.messages):
            if message.get("role") == "assistant":
                content = message.get("content", "")
                if content and self._looks_like_report(content):
                    return self._extract_report(content)
        
        # 如果没找到，返回空或最后的 assistant 内容
        for message in reversed(self.state.messages):
            if message.get("role") == "assistant" and message.get("content"):
                return message.get("content", "")
        
        return ""
    
    def _extract_report(self, content: str) -> str:
        """提取最终报告"""
        import re
        
        # 清理可能的结束标记（兼容旧格式）
        report = content.replace("[ANALYSIS_COMPLETE]", "").strip()
        
        # 移除末尾的分隔线
        report = re.sub(r'\n---\s*$', '', report)
        
        return report.strip()
    
    # ============================================================
    # 工具处理
    # ============================================================
    
    async def _handle_tool_call(self, response: Dict[str, Any], iteration_duration: float = 0):
        """处理工具调用"""
        tool_name = response["name"]
        arguments = response["arguments"]
        tool_call_id = response.get("tool_call_id", f"call_{self.state.iteration}")
        content = response.get("content", "")
        reasoning = response.get("reasoning")  # 获取模型思考过程
        
        logger.info(f"[ToolDrivenAgent] 工具调用: {tool_name}")
        
        # 只在有模型原生思考过程时才发送思考事件（避免与 content 重复）
        if reasoning:
            await self.emit_event("llm_thinking", {
                "thinking": reasoning,  # 不截断，发送完整内容
                "is_real": True,
                "is_reasoning": True,
                "iteration": self.state.iteration,
                "duration": iteration_duration
            })
            logger.info(f"[ToolDrivenAgent] 🧠 模型思考: {reasoning[:200]}...")
        
        await self.emit_event("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "iteration": self.state.iteration
        })
        
        tool_start = time.time()
        
        # 执行工具
        if tool_name == "read_dataset":
            result = await self._execute_read_dataset(arguments)
            
        elif tool_name == "run_code":
            result = await self._execute_run_code(arguments)
            
        elif tool_name == "todo_write":
            result = await self._execute_todo_write(arguments)
            
        else:
            logger.warning(f"[ToolDrivenAgent] 未知工具: {tool_name}")
            result = {"status": "error", "message": f"未知工具: {tool_name}"}
        
        tool_duration = time.time() - tool_start
        
        logger.info(f"[ToolDrivenAgent] 工具执行完成 ({tool_duration:.2f}秒): {result.get('status')}")
        
        # 构建工具结果
        tool_result_str = self._build_tool_result(tool_name, result)
        
        await self.emit_event("tool_result", {
            "tool": tool_name,
            "status": result.get("status"),
            "has_image": result.get("has_image", False),
            "stdout_preview": (result.get("stdout") or "")[:500],  # 添加输出预览
            "duration": tool_duration,
            "iteration": self.state.iteration  # 添加迭代号
        })
        
        # 添加到消息历史
        # 注意：将 reasoning 拼接到 content 中，保持上下文连贯性
        # 这对于思考型模型（如 kimi-k2-thinking）很重要，否则模型可能"遗忘"之前的决策逻辑
        assistant_content = content if content else ""
        if reasoning:
            # 将思考过程作为上下文的一部分保留
            # 格式：[思考过程] + 实际内容
            if assistant_content:
                assistant_content = f"[思考：{reasoning[:500]}...]\n\n{assistant_content}" if len(reasoning) > 500 else f"[思考：{reasoning}]\n\n{assistant_content}"
            else:
                assistant_content = f"[思考：{reasoning[:500]}...]" if len(reasoning) > 500 else f"[思考：{reasoning}]"
        
        self.state.messages.append({
            "role": "assistant",
            "content": assistant_content if assistant_content else None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False)
                }
            }]
        })
        
        self.state.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_result_str
        })
    
    async def _execute_read_dataset(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 read_dataset 工具"""
        logger.info(f"[ToolDrivenAgent] 执行 read_dataset...")
        
        result = tool_read_dataset(
            self.dataset_path,
            preview_rows=arguments.get("preview_rows", 5)
        )
        
        if result.get("status") == "success":
            await self.emit_event("data_explored", {
                "schema": result.get("schema", []),
                "statistics": result.get("statistics", {}),
                "preview": result.get("preview", [])[:3]
            })
        
        return result
    
    async def _execute_run_code(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 run_code 工具"""
        code = arguments.get("code", "")
        description = arguments.get("description", "")
        
        logger.info(f"[ToolDrivenAgent] 执行 run_code: {description[:50]}...")
        
        await self.emit_event("code_generated", {
            "code": code,
            "description": description,
            "iteration": self.state.iteration
        })
        
        result = tool_run_code(code, self.dataset_path, description=description)
        
        # 如果有图片，保存并发送
        if result.get("image_base64"):
            logger.info(f"[ToolDrivenAgent] 生成了图表")
            self.state.images.append({
                "iteration": self.state.iteration,
                "image_base64": result["image_base64"],
                "description": description
            })
            
            await self.emit_event("image_generated", {
                "image_base64": result["image_base64"],
                "iteration": self.state.iteration
            })
        
        # 记录分析结果
        self.state.analysis_results.append({
            "iteration": self.state.iteration,
            "description": description,
            "stdout": result.get("stdout", "")[:500]
        })
        
        return result
    
    async def _execute_todo_write(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 todo_write 工具
        
        这是任务状态同步的核心工具。
        每次调用后检查：如果所有任务都是 completed，则验收通过。
        """
        todos = arguments.get("todos", [])
        merge = arguments.get("merge", True)
        
        logger.info(f"[ToolDrivenAgent] 执行 todo_write: {len(todos)} 个任务, merge={merge}")
        
        if not merge:
            # 完全覆盖模式：清空现有任务，创建新任务
            self.state.tasks = []
            self.report_validated = False  # 重置验收状态
            logger.info(f"[ToolDrivenAgent]   清空现有任务，创建新清单")
        
        updated_tasks = []
        
        for todo in todos:
            task_id = int(todo["id"])
            task_content = todo["content"]
            task_status = TaskStatus(todo["status"])
            
            existing_task = self.state.get_task(task_id)
            
            if existing_task:
                # 更新现有任务
                old_status = existing_task.status
                existing_task.name = task_content
                existing_task.status = task_status
                
                # 记录状态变化
                if old_status != task_status:
                    logger.info(f"[ToolDrivenAgent]   任务 [{task_id}] {task_content}: {old_status.value} → {task_status.value}")
                
                updated_tasks.append({
                    "id": task_id,
                    "content": task_content,
                    "status": task_status.value,
                    "changed": old_status != task_status
                })
            else:
                # 创建新任务
                new_task = Task(
                    id=task_id,
                    name=task_content,
                    description="",
                    type="analysis",
                    status=task_status
                )
                self.state.tasks.append(new_task)
                
                logger.info(f"[ToolDrivenAgent]   新增任务 [{task_id}] {task_content}: {task_status.value}")
                
                updated_tasks.append({
                    "id": task_id,
                    "content": task_content,
                    "status": task_status.value,
                    "changed": True
                })
        
        # 核心验收逻辑：检查是否所有任务都已完成
        incomplete_tasks = self._get_incomplete_tasks()
        all_completed = len(incomplete_tasks) == 0 and len(self.state.tasks) > 0
        
        if all_completed and not self.report_validated:
            self.report_validated = True
            logger.info(f"[ToolDrivenAgent] ✅ 任务闭环完成！所有 {len(self.state.tasks)} 个任务都已标记为 completed")
        elif not all_completed:
            logger.info(f"[ToolDrivenAgent]   当前进度: {len(self.state.tasks) - len(incomplete_tasks)}/{len(self.state.tasks)} 任务已完成")
        
        # 发送任务更新事件
        await self.emit_event("tasks_updated", {
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "status": t.status.value,
                    "description": t.description,
                    "type": t.type
                }
                for t in self.state.tasks
            ],
            "source": "tool",  # 标记来源是工具调用
            "all_completed": all_completed,
            "report_validated": self.report_validated
        })
        
        # 构建返回结果
        completed_count = len([t for t in self.state.tasks if t.status == TaskStatus.COMPLETED])
        pending_count = len([t for t in self.state.tasks if t.status == TaskStatus.PENDING])
        in_progress_count = len([t for t in self.state.tasks if t.status == TaskStatus.IN_PROGRESS])
        
        result = {
            "status": "success",
            "message": f"任务清单已更新",
            "summary": {
                "total": len(self.state.tasks),
                "completed": completed_count,
                "in_progress": in_progress_count,
                "pending": pending_count
            },
            "updated": updated_tasks
        }
        
        # 如果所有任务完成，在返回结果中明确告知
        if all_completed:
            result["task_loop_closed"] = {
                "completed": True,
                "message": "所有任务已完成，分析任务闭环"
            }
        
        return result
    
    def _build_tool_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        """构建工具结果字符串"""
        if tool_name == "read_dataset":
            if result.get("status") == "success":
                return json.dumps({
                    "status": "success",
                    "schema": result.get("schema", []),
                    "statistics": result.get("statistics", {}),
                    "preview": result.get("preview", [])[:5]
                }, ensure_ascii=False, indent=2)
            else:
                return json.dumps(result, ensure_ascii=False)
        
        elif tool_name == "run_code":
            return json.dumps({
                "status": result.get("status"),
                "stdout": (result.get("stdout") or "")[:2000],
                "stderr": (result.get("stderr") or "")[:500],
                "has_image": result.get("has_image", False)
            }, ensure_ascii=False, indent=2)
        
        elif tool_name == "todo_write":
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        else:
            return json.dumps(result, ensure_ascii=False)

