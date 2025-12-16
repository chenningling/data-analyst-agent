"""
任务驱动自主循环 Agent 模块（优化版）

核心改进：
1. 以任务为单位的循环结构（不再是扁平迭代）
2. 代码层控制流程，LLM 负责执行
3. 每个任务完成后有验收步骤
4. 明确的结束条件：所有任务完成 或 达到最大循环数
5. todo_write 工具化管理任务

执行流程：
- Phase 1: 读取数据 → 创建任务清单（todo_write）
- Phase 2: 以任务为单位循环执行
  - 注入当前任务上下文 → LLM 执行 → 验收 → 标记完成
- Phase 3: 生成最终报告
"""
import json
import re
import uuid
import time
from typing import Callable, Dict, Any, Optional, List, Awaitable
from datetime import datetime

from agent.state import AgentState, AgentPhase, Task, TaskStatus
from agent.llm_client import get_llm_client, LLMClient
from tools import tool_read_dataset, tool_run_code
from config.settings import settings
from utils.logger import logger


# ============================================================
# 工具 Schema（包含 todo_write）
# ============================================================

TASK_DRIVEN_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_dataset",
            "description": "读取上传的数据集，返回数据预览、列信息和基本统计信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "preview_rows": {
                        "type": "integer",
                        "description": "预览的行数，默认为 5",
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
            "description": "执行 Python 代码进行数据分析。使用 pandas 读取数据，matplotlib 绑图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码"
                    },
                    "description": {
                        "type": "string",
                        "description": "代码功能的简要描述"
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
            "description": "管理分析任务清单：创建任务、更新状态。首次规划用 merge=false，后续更新用 merge=true。",
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
                                    "description": "唯一标识符（如 '1'、'2'）"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "任务内容（动词开头，≤14 字）"
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
                        "description": "true=增量更新，false=完全覆盖"
                    }
                },
                "required": ["todos", "merge"]
            }
        }
    }
]


# ============================================================
# 提示词模板
# ============================================================

TASK_DRIVEN_SYSTEM_PROMPT = """你是一个专业的数据分析 Agent。按照系统指定的任务逐步完成数据分析。

## 可用工具
- `read_dataset`: 读取数据结构和预览
- `run_code`: 执行 Python 代码进行分析
- `todo_write`: 管理任务清单（创建/更新任务状态）

## 代码编写规范
- 数据读取：`pd.read_excel('{dataset_path}')` 或 `pd.read_csv(...)`
- 中文支持：`plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']`
- 图表保存：`plt.savefig('result.png', dpi=150, bbox_inches='tight')`
- 打印关键结果到 stdout

## 重要规则
1. 每次只专注于完成当前指定的任务
2. 任务完成后会由系统验收，无需自行判断
3. 确保代码能够正确执行
4. 分析结论要有数据支撑
"""

PLANNING_PHASE_PROMPT = """请分析以下数据集和用户需求，规划分析任务清单。

## 数据文件路径
{dataset_path}

## 用户分析需求
{user_request}

## 数据结构
{data_schema}

## 执行步骤
1. 首先调用 `todo_write` 创建任务清单（merge=false）
2. 任务数量控制在 3-5 个
3. 每个任务要具体、可执行
4. 任务按逻辑顺序：数据探索 → 核心分析 → 可视化

示例：
调用 todo_write，参数：
{{
  "todos": [
    {{"id": "1", "content": "探索数据基本特征", "status": "pending"}},
    {{"id": "2", "content": "分析销售趋势", "status": "pending"}},
    {{"id": "3", "content": "生成趋势可视化", "status": "pending"}}
  ],
  "merge": false
}}
"""

TASK_EXECUTION_PROMPT = """## 当前任务

**任务ID**: {task_id}
**任务内容**: {task_content}
**任务状态**: {task_status}

## 已完成的任务
{completed_tasks}

## 数据文件路径
{dataset_path}

## 执行要求
请专注于完成当前任务，调用 `run_code` 执行分析代码。

代码编写注意事项：
- 数据读取：`pd.read_excel('{dataset_path}')`
- 中文支持：`plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']`
- 图表保存：`plt.savefig('result.png', dpi=150, bbox_inches='tight')`
- 打印关键结果

请开始执行任务。
"""

TASK_VERIFICATION_PROMPT = """## 任务验收

请检查任务 [{task_id}] "{task_content}" 的执行结果。

## 代码执行结果
{execution_result}

## 判断标准
1. 任务目标是否达成？
2. 是否有明确的分析结果或可视化输出？
3. 执行是否有错误？

## 回复要求
根据验收结果，调用 `todo_write` 工具更新任务状态：

- 如果任务成功完成，调用 todo_write 将任务状态更新为 "completed"：
  {{"todos": [{{"id": "{task_id}", "content": "{task_content}", "status": "completed"}}], "merge": true}}

- 如果任务失败需要重试，直接回复 `[TASK_RETRY]` 并说明原因（不要调用工具）
"""

REPORT_GENERATION_PROMPT = """请根据所有分析结果生成最终的数据分析报告。

## 用户原始需求
{user_request}

## 任务完成情况
{task_summary}

## 分析结果汇总
{analysis_results}

## 图表数量
共生成 {image_count} 个图表

## 报告要求
1. 使用 Markdown 格式
2. 报告结构：
   - 📊 **数据概览**
   - 🔍 **关键发现**
   - 📈 **分析详情**
   - 💡 **洞察与建议**
   - 📋 **总结**
3. 确保每个结论都有数据支撑
4. 语言简洁专业

请生成报告。
"""


class TaskDrivenAgentLoop:
    """任务驱动自主循环 Agent（代码控制 + 工具化任务管理）"""
    
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
            {"role": "system", "content": TASK_DRIVEN_SYSTEM_PROMPT}
        ]
        
        # 配置
        self.max_iterations = settings.MAX_ITERATIONS
        self.max_retries_per_task = 3  # 每个任务最大重试次数
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"[TaskDrivenAgent] 初始化")
        logger.info(f"[TaskDrivenAgent] Session: {self.state.session_id}")
        logger.info(f"[TaskDrivenAgent] 数据集: {dataset_path}")
        logger.info(f"[TaskDrivenAgent] 用户需求: {user_request[:100]}...")
        logger.info(f"{'#'*60}\n")
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """发送事件到前端"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.state.session_id,
            "payload": payload
        }
        logger.info(f"[TaskDrivenAgent] 发送事件: {event_type}")
        await self.event_callback(event)
    
    # ============================================================
    # 主运行循环
    # ============================================================
    
    async def run(self) -> Dict[str, Any]:
        """运行任务驱动循环"""
        self.start_time = time.time()
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[TaskDrivenAgent] ===== 开始执行 =====")
        logger.info(f"[TaskDrivenAgent] 最大迭代数: {self.max_iterations}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request,
                "mode": "task_driven"
            })
            
            # ========== Phase 1: 规划阶段 ==========
            logger.info(f"\n[TaskDrivenAgent] ===== Phase 1: 规划阶段 =====")
            await self.emit_event("phase_change", {"phase": "planning"})
            self.state.phase = AgentPhase.PLANNING
            
            await self._phase_planning()
            
            # ========== Phase 2: 执行阶段（任务驱动循环）==========
            logger.info(f"\n[TaskDrivenAgent] ===== Phase 2: 执行阶段 =====")
            await self.emit_event("phase_change", {"phase": "executing"})
            self.state.phase = AgentPhase.EXECUTING
            
            await self._phase_execution()
            
            # ========== Phase 3: 报告阶段 ==========
            logger.info(f"\n[TaskDrivenAgent] ===== Phase 3: 报告阶段 =====")
            await self.emit_event("phase_change", {"phase": "reporting"})
            self.state.phase = AgentPhase.REPORTING
            
            await self._phase_reporting()
            
            # 完成
            self.state.phase = AgentPhase.COMPLETED
            self.state.completed_at = datetime.utcnow()
            total_time = time.time() - self.start_time
            
            logger.info(f"\n{'*'*60}")
            logger.info(f"[TaskDrivenAgent] ===== 执行完成 =====")
            logger.info(f"[TaskDrivenAgent] 总耗时: {total_time:.2f}秒")
            logger.info(f"[TaskDrivenAgent] 总迭代次数: {self.state.iteration}")
            logger.info(f"[TaskDrivenAgent] 任务完成: {self._get_completion_stats()}")
            logger.info(f"{'*'*60}\n")
            
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
            logger.error(f"[TaskDrivenAgent] 执行失败: {e}")
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
    
    # ============================================================
    # Phase 1: 规划阶段
    # ============================================================
    
    async def _phase_planning(self):
        """规划阶段：读取数据 + 创建任务清单"""
        
        # Step 1: 读取数据结构
        logger.info(f"[TaskDrivenAgent] Step 1: 读取数据结构")
        await self.emit_event("llm_thinking", {
            "thinking": "正在读取数据集，了解数据结构...",
            "phase": "planning"
        })
        
        data_info = tool_read_dataset(self.dataset_path, preview_rows=5)
        
        if data_info["status"] == "error":
            raise Exception(f"读取数据失败: {data_info.get('message')}")
        
        await self.emit_event("data_explored", {
            "schema": data_info["schema"],
            "statistics": data_info["statistics"],
            "preview": data_info["preview"][:3]
        })
        
        # Step 2: 让 LLM 创建任务清单
        logger.info(f"[TaskDrivenAgent] Step 2: 创建任务清单")
        await self.emit_event("llm_thinking", {
            "thinking": "正在分析需求，规划任务清单...",
            "phase": "planning"
        })
        
        # 构建数据结构描述
        schema_desc = json.dumps(data_info["schema"], ensure_ascii=False, indent=2)
        stats_desc = json.dumps(data_info["statistics"], ensure_ascii=False, indent=2)
        data_schema = f"列信息:\n{schema_desc}\n\n统计:\n{stats_desc}"
        
        planning_prompt = PLANNING_PHASE_PROMPT.format(
            dataset_path=self.dataset_path,
            user_request=self.user_request,
            data_schema=data_schema
        )
        
        self.state.messages.append({"role": "user", "content": planning_prompt})
        self.state.iteration += 1
        
        # 调用 LLM（期望调用 todo_write 工具）
        response = self.llm.chat(self.state.messages, tools=TASK_DRIVEN_TOOLS_SCHEMA)
        
        if response["type"] == "error":
            raise Exception(f"任务规划失败: {response['error']}")
        
        # 处理 todo_write 工具调用
        if response["type"] == "tool_call" and response["name"] == "todo_write":
            await self._handle_todo_write(response)
        else:
            # 如果 LLM 没有调用 todo_write，尝试从文本中解析
            logger.warning(f"[TaskDrivenAgent] LLM 未调用 todo_write，尝试重新引导")
            # 添加更明确的引导
            self.state.messages.append({
                "role": "user", 
                "content": "请调用 todo_write 工具创建任务清单。"
            })
            response = self.llm.chat(self.state.messages, tools=TASK_DRIVEN_TOOLS_SCHEMA)
            
            if response["type"] == "tool_call" and response["name"] == "todo_write":
                await self._handle_todo_write(response)
            else:
                raise Exception("无法创建任务清单")
        
        logger.info(f"[TaskDrivenAgent] 任务规划完成: {len(self.state.tasks)} 个任务")
    
    # ============================================================
    # Phase 2: 执行阶段（任务驱动循环）
    # ============================================================
    
    async def _phase_execution(self):
        """执行阶段：以任务为单位循环执行"""
        
        logger.info(f"[TaskDrivenAgent] 开始任务驱动循环")
        logger.info(f"[TaskDrivenAgent] 待执行任务数: {len(self.state.tasks)}")
        
        # 获取待执行的任务
        pending_tasks = [t for t in self.state.tasks if t.status == TaskStatus.PENDING]
        
        for task in pending_tasks:
            # 检查是否达到最大迭代数
            if self.state.iteration >= self.max_iterations:
                logger.warning(f"[TaskDrivenAgent] 达到最大迭代数 {self.max_iterations}，终止执行")
                break
            
            # 执行单个任务
            await self._execute_single_task(task)
            
            # 检查结束条件
            if self._check_completion_condition():
                logger.info(f"[TaskDrivenAgent] 所有任务已完成")
                break
        
        # 汇总执行情况
        logger.info(f"[TaskDrivenAgent] 执行阶段完成: {self._get_completion_stats()}")
    
    async def _execute_single_task(self, task: Task):
        """执行单个任务（包含重试机制）"""
        
        retry_count = 0
        task_completed = False
        
        # 更新任务状态为进行中
        self.state.current_task_id = task.id
        self.state.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        
        logger.info(f"\n[TaskDrivenAgent] ----- 开始任务 [{task.id}]: {task.name} -----")
        
        await self.emit_event("task_started", {
            "task_id": task.id,
            "task_name": task.name
        })
        await self._emit_tasks_status()
        
        task_start_time = time.time()
        
        while retry_count < self.max_retries_per_task and not task_completed:
            self.state.iteration += 1
            retry_count += 1
            
            logger.info(f"[TaskDrivenAgent] 任务 [{task.id}] 尝试 {retry_count}/{self.max_retries_per_task}")
            
            try:
                # Step 1: 注入任务上下文，让 LLM 执行
                execution_result = await self._task_execute(task)
                
                # Step 2: 验收任务结果（LLM 会调用 todo_write 更新状态）
                verified = await self._task_verify(task, execution_result)
                
                if verified:
                    # 验收通过（状态已由 todo_write 或兜底逻辑更新）
                    task.result = execution_result
                    task_completed = True
                    
                    logger.info(f"[TaskDrivenAgent] ✅ 任务 [{task.id}] 验收通过")
                else:
                    logger.info(f"[TaskDrivenAgent] ⚠️ 任务 [{task.id}] 需要重试")
                    
            except Exception as e:
                logger.error(f"[TaskDrivenAgent] 任务 [{task.id}] 执行异常: {e}", exc_info=True)
        
        task_duration = time.time() - task_start_time
        
        if not task_completed:
            self.state.update_task_status(task.id, TaskStatus.FAILED, error="超过最大重试次数")
            logger.error(f"[TaskDrivenAgent] ❌ 任务 [{task.id}] 执行失败")
            
            await self.emit_event("task_failed", {
                "task_id": task.id,
                "task_name": task.name,
                "duration": task_duration
            })
        else:
            await self.emit_event("task_completed", {
                "task_id": task.id,
                "task_name": task.name,
                "duration": task_duration
            })
        
        await self._emit_tasks_status()
    
    async def _task_execute(self, task: Task) -> Dict[str, Any]:
        """任务执行：让 LLM 调用 run_code"""
        
        await self.emit_event("llm_thinking", {
            "thinking": f"正在执行任务 [{task.id}] {task.name}...",
            "phase": "executing",
            "task_id": task.id
        })
        
        # 构建任务执行提示
        completed_tasks = self._get_completed_tasks_summary()
        
        task_prompt = TASK_EXECUTION_PROMPT.format(
            task_id=task.id,
            task_content=task.name,
            task_status="in_progress",
            completed_tasks=completed_tasks,
            dataset_path=self.dataset_path
        )
        
        self.state.messages.append({"role": "user", "content": task_prompt})
        
        # 调用 LLM
        response = self.llm.chat(self.state.messages, tools=TASK_DRIVEN_TOOLS_SCHEMA)
        
        if response["type"] == "error":
            raise Exception(f"LLM 调用失败: {response['error']}")
        
        # 处理工具调用
        if response["type"] == "tool_call":
            result = await self._handle_tool_call(task, response)
            return result
        else:
            # LLM 返回文本而非工具调用
            self.state.messages.append({"role": "assistant", "content": response["content"]})
            return {"type": "text", "content": response["content"]}
    
    async def _task_verify(self, task: Task, execution_result: Dict[str, Any]) -> bool:
        """任务验收：检查执行结果是否满足任务目标，并通过 todo_write 更新状态"""
        
        logger.info(f"[TaskDrivenAgent] 验收任务 [{task.id}]...")
        
        # 构建验收提示
        result_summary = json.dumps(execution_result, ensure_ascii=False, indent=2)[:2000]
        
        verification_prompt = TASK_VERIFICATION_PROMPT.format(
            task_id=task.id,
            task_content=task.name,
            execution_result=result_summary
        )
        
        self.state.messages.append({"role": "user", "content": verification_prompt})
        
        # 调用 LLM 验收（带工具，期望调用 todo_write）
        response = self.llm.chat(self.state.messages, tools=TASK_DRIVEN_TOOLS_SCHEMA)
        
        if response["type"] == "error":
            logger.warning(f"[TaskDrivenAgent] 验收调用失败: {response['error']}")
            return False
        
        # 处理工具调用（期望是 todo_write）
        if response["type"] == "tool_call":
            if response["name"] == "todo_write":
                # LLM 调用了 todo_write 更新任务状态
                await self._handle_todo_write(response)
                
                # 检查任务状态是否已更新为 completed
                updated_task = self.state.get_task(task.id)
                if updated_task and updated_task.status == TaskStatus.COMPLETED:
                    logger.info(f"[TaskDrivenAgent] ✅ 任务 [{task.id}] 通过 todo_write 标记完成")
                    
                    await self.emit_event("llm_thinking", {
                        "thinking": f"[验收通过] 任务 [{task.id}] 已通过 todo_write 标记为完成",
                        "phase": "verification",
                        "task_id": task.id
                    })
                    return True
                else:
                    logger.info(f"[TaskDrivenAgent] 任务 [{task.id}] 状态: {updated_task.status if updated_task else 'unknown'}")
                    return False
            else:
                # 调用了其他工具，可能是需要继续执行
                logger.info(f"[TaskDrivenAgent] 验收时调用了其他工具: {response['name']}")
                await self._handle_tool_call(task, response)
                return False
        
        # 处理文本响应
        content = response["content"]
        self.state.messages.append({"role": "assistant", "content": content})
        
        await self.emit_event("llm_thinking", {
            "thinking": f"[验收] {content[:200]}...",
            "phase": "verification",
            "task_id": task.id
        })
        
        # 检查验收结果
        if "[TASK_RETRY]" in content:
            return False
        else:
            # 如果 LLM 没有调用 todo_write 但也没说重试，检查执行结果
            if execution_result.get("status") == "success":
                # 代码层兜底：手动更新任务状态
                logger.info(f"[TaskDrivenAgent] LLM 未调用 todo_write，代码层兜底更新状态")
                self.state.update_task_status(task.id, TaskStatus.COMPLETED)
                return True
            return False
    
    # ============================================================
    # Phase 3: 报告阶段
    # ============================================================
    
    async def _phase_reporting(self):
        """报告阶段：生成最终分析报告"""
        
        logger.info(f"[TaskDrivenAgent] 开始生成报告")
        
        await self.emit_event("llm_thinking", {
            "thinking": "正在汇总所有分析结果，生成最终报告...",
            "phase": "reporting"
        })
        
        # 汇总分析结果
        results_summary = json.dumps(
            self.state.analysis_results,
            ensure_ascii=False,
            indent=2
        )
        
        task_summary = self.state.get_tasks_summary()
        
        report_prompt = REPORT_GENERATION_PROMPT.format(
            user_request=self.user_request,
            task_summary=task_summary,
            analysis_results=results_summary,
            image_count=len(self.state.images)
        )
        
        self.state.messages.append({"role": "user", "content": report_prompt})
        self.state.iteration += 1
        
        # 生成报告
        response = self.llm.chat(self.state.messages)
        
        if response["type"] == "error":
            self.state.final_report = f"# 分析报告\n\n报告生成失败: {response['error']}"
        else:
            self.state.final_report = response["content"]
        
        logger.info(f"[TaskDrivenAgent] 报告生成完成，长度: {len(self.state.final_report)} 字符")
        
        await self.emit_event("report_generated", {
            "report": self.state.final_report
        })
    
    # ============================================================
    # 工具处理
    # ============================================================
    
    async def _handle_tool_call(self, task: Task, response: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具调用"""
        
        tool_name = response["name"]
        arguments = response["arguments"]
        tool_call_id = response.get("tool_call_id", f"call_{self.state.iteration}")
        
        logger.info(f"[TaskDrivenAgent] 工具调用: {tool_name}")
        
        await self.emit_event("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "task_id": task.id if task else None
        })
        
        tool_start = time.time()
        
        # 执行工具
        if tool_name == "read_dataset":
            result = tool_read_dataset(
                self.dataset_path,
                preview_rows=arguments.get("preview_rows", 5)
            )
            
        elif tool_name == "run_code":
            code = arguments.get("code", "")
            description = arguments.get("description", "")
            
            if task:
                task.code = code
            
            await self.emit_event("code_generated", {
                "code": code,
                "description": description,
                "task_id": task.id if task else None
            })
            
            result = tool_run_code(code, self.dataset_path, description=description)
            
            # 处理图片
            if result.get("image_base64"):
                self.state.images.append({
                    "task_id": task.id if task else None,
                    "task_name": task.name if task else "",
                    "image_base64": result["image_base64"],
                    "description": description
                })
                
                await self.emit_event("image_generated", {
                    "image_base64": result["image_base64"],
                    "task_id": task.id if task else None
                })
                
        elif tool_name == "todo_write":
            result = await self._handle_todo_write(response)
            
        else:
            result = {"status": "error", "message": f"未知工具: {tool_name}"}
        
        tool_duration = time.time() - tool_start
        
        logger.info(f"[TaskDrivenAgent] 工具执行完成 ({tool_duration:.2f}秒): {result.get('status')}")
        
        # 构建结果摘要
        tool_result_summary = {
            "tool": tool_name,
            "status": result.get("status"),
            "stdout": (result.get("stdout") or "")[:2000],
            "stderr": (result.get("stderr") or "")[:500],
            "has_image": result.get("has_image", False)
        }
        
        await self.emit_event("tool_result", {
            "tool": tool_name,
            "status": result.get("status"),
            "has_image": result.get("has_image", False),
            "duration": tool_duration
        })
        
        # 添加到消息历史
        self.state.messages.append({
            "role": "assistant",
            "content": None,
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
            "content": json.dumps(tool_result_summary, ensure_ascii=False)
        })
        
        # 保存分析结果
        if task and tool_name == "run_code":
            self.state.analysis_results.append({
                "task_id": task.id,
                "task_name": task.name,
                "tool": tool_name,
                "result": tool_result_summary
            })
        
        return result
    
    async def _handle_todo_write(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """处理 todo_write 工具调用"""
        
        arguments = response["arguments"]
        todos = arguments.get("todos", [])
        merge = arguments.get("merge", True)
        
        logger.info(f"[TaskDrivenAgent] todo_write: {len(todos)} 个任务, merge={merge}")
        
        if not merge:
            # 完全覆盖模式
            self.state.tasks = []
        
        for todo in todos:
            task_id = int(todo["id"])
            task_content = todo["content"]
            task_status = TaskStatus(todo["status"])
            
            existing_task = self.state.get_task(task_id)
            
            if existing_task:
                # 更新现有任务
                existing_task.name = task_content
                existing_task.status = task_status
                logger.info(f"[TaskDrivenAgent]   更新任务 [{task_id}]: {task_content} -> {task_status.value}")
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
                logger.info(f"[TaskDrivenAgent]   新增任务 [{task_id}]: {task_content}")
        
        # 发送任务更新事件
        await self._emit_tasks_status()
        
        # 添加到消息历史
        tool_call_id = response.get("tool_call_id", f"call_{self.state.iteration}")
        
        self.state.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": "todo_write",
                    "arguments": json.dumps(arguments, ensure_ascii=False)
                }
            }]
        })
        
        self.state.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps({"status": "success", "tasks_count": len(self.state.tasks)}, ensure_ascii=False)
        })
        
        return {"status": "success", "tasks_count": len(self.state.tasks)}
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _check_completion_condition(self) -> bool:
        """检查是否满足结束条件"""
        if not self.state.tasks:
            return False
        
        # 条件1: 所有任务完成或取消
        all_done = all(
            t.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED]
            for t in self.state.tasks
        )
        
        # 条件2: 达到最大迭代数
        max_reached = self.state.iteration >= self.max_iterations
        
        return all_done or max_reached
    
    def _get_completion_stats(self) -> str:
        """获取完成统计"""
        completed = len([t for t in self.state.tasks if t.status == TaskStatus.COMPLETED])
        failed = len([t for t in self.state.tasks if t.status == TaskStatus.FAILED])
        total = len(self.state.tasks)
        return f"{completed}/{total} 完成, {failed} 失败"
    
    def _get_completed_tasks_summary(self) -> str:
        """获取已完成任务摘要"""
        completed = self.state.get_completed_tasks()
        if not completed:
            return "无"
        
        summaries = []
        for t in completed:
            result_summary = ""
            if t.result:
                if isinstance(t.result, dict):
                    result_summary = (t.result.get("stdout") or "")[:100]
                else:
                    result_summary = str(t.result)[:100]
            summaries.append(f"- [{t.id}] {t.name}: {result_summary or '完成'}")
        
        return "\n".join(summaries)
    
    async def _emit_tasks_status(self):
        """发送任务状态更新事件"""
        tasks_data = [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.value,
                "description": t.description,
                "type": t.type
            }
            for t in self.state.tasks
        ]
        
        await self.emit_event("tasks_updated", {
            "tasks": tasks_data,
            "source": "task_driven"
        })

