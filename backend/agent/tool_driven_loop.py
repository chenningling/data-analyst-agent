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
3. **todo_write** - 管理任务清单（核心工具）

## todo_write 工具使用指南

### 1. 创建任务清单（分析开始时）
读取数据后，调用 todo_write 创建任务清单：
```json
{{
  "todos": [
    {{"id": "1", "content": "探索数据基本特征", "status": "pending"}},
    {{"id": "2", "content": "分析销售趋势", "status": "pending"}},
    {{"id": "3", "content": "生成可视化图表", "status": "pending"}}
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

### 3. 完成任务
任务执行成功后，标记为 completed：
```json
{{
  "todos": [{{"id": "1", "content": "探索数据基本特征", "status": "completed"}}],
  "merge": true
}}
```

## 完整工作流程

1. **了解数据**：调用 `read_dataset` 读取数据结构
2. **创建任务清单**：调用 `todo_write`（merge=false）创建 3-5 个任务
3. **逐个执行任务**：
   - 调用 `todo_write` 标记任务为 in_progress
   - 调用 `run_code` 执行分析代码
   - 调用 `todo_write` 标记任务为 completed
4. **输出报告**：所有任务完成后，直接输出 Markdown 格式的分析报告

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

## 重要规则

1. **任务状态必须通过 todo_write 更新** - 每个任务开始前标记 in_progress，完成后标记 completed
2. **按顺序执行任务** - 一次只执行一个任务
3. **所有任务完成后才输出报告** - 确保每个任务都是 completed 状态
4. **报告末尾添加结束标记** - `[ANALYSIS_COMPLETE]`

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

---
[ANALYSIS_COMPLETE]
```
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
        self.llm = get_llm_client()
        self.start_time = None
        
        # Agent 状态
        self.state = AgentState(
            session_id=str(uuid.uuid4()),
            dataset_path=dataset_path,
            user_request=user_request
        )
        
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
        运行工具驱动循环
        
        核心逻辑：只发一条消息，让 LLM 自主完成所有工作
        """
        self.start_time = time.time()
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[ToolDrivenAgent] ===== 开始执行 =====")
        logger.info(f"[ToolDrivenAgent] 最大迭代数: {self.max_iterations}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request,
                "mode": "tool_driven"
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
                
                # 调用 LLM
                response = self.llm.chat(
                    self.state.messages,
                    tools=TOOL_DRIVEN_TOOLS_SCHEMA
                )
                
                iteration_duration = time.time() - iteration_start
                
                if response["type"] == "error":
                    logger.error(f"[ToolDrivenAgent] LLM 调用失败: {response['error']}")
                    raise Exception(f"LLM 调用失败: {response['error']}")
                
                if response["type"] == "tool_call":
                    # 执行工具
                    await self._handle_tool_call(response, iteration_duration)
                    
                else:
                    # LLM 输出文本（可能是最终报告）
                    content = response["content"]
                    self.state.messages.append({"role": "assistant", "content": content})
                    
                    # 发送思考事件
                    await self.emit_event("llm_thinking", {
                        "thinking": content[:500] + ("..." if len(content) > 500 else ""),
                        "is_real": True,
                        "iteration": self.state.iteration,
                        "duration": iteration_duration
                    })
                    
                    # 检查是否完成
                    if self._is_complete(content):
                        logger.info(f"[ToolDrivenAgent] ✅ 检测到分析完成标记")
                        self.state.final_report = self._extract_report(content)
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
    
    def _is_complete(self, content: str) -> bool:
        """检查分析是否完成"""
        return "[ANALYSIS_COMPLETE]" in content
    
    def _extract_report(self, content: str) -> str:
        """提取最终报告"""
        # 移除结束标记
        report = content.replace("[ANALYSIS_COMPLETE]", "").strip()
        # 移除末尾的分隔线
        import re
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
        
        logger.info(f"[ToolDrivenAgent] 工具调用: {tool_name}")
        
        # 如果有思考内容，发送事件
        if content:
            await self.emit_event("llm_thinking", {
                "thinking": content[:300] + ("..." if len(content) > 300 else ""),
                "is_real": True,
                "iteration": self.state.iteration,
                "duration": iteration_duration
            })
        
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
            "duration": tool_duration
        })
        
        # 添加到消息历史
        self.state.messages.append({
            "role": "assistant",
            "content": content if content else None,
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
        
        这是核心：LLM 通过这个工具自主管理任务状态
        """
        todos = arguments.get("todos", [])
        merge = arguments.get("merge", True)
        
        logger.info(f"[ToolDrivenAgent] 执行 todo_write: {len(todos)} 个任务, merge={merge}")
        
        if not merge:
            # 完全覆盖模式：清空现有任务，创建新任务
            self.state.tasks = []
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
            "source": "tool"  # 标记来源是工具调用
        })
        
        # 构建返回结果
        completed_count = len([t for t in self.state.tasks if t.status == TaskStatus.COMPLETED])
        pending_count = len([t for t in self.state.tasks if t.status == TaskStatus.PENDING])
        in_progress_count = len([t for t in self.state.tasks if t.status == TaskStatus.IN_PROGRESS])
        
        return {
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

