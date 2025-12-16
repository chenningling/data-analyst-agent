"""
混合模式 Agent 循环模块

结合自主模式的灵活性和分阶段模式的可控性：
- Phase 1: 数据探索 + 任务规划（LLM 生成 JSON 格式任务清单，代码解析存储）
- Phase 2: 任务驱动循环（代码控制执行顺序，每个任务内允许 LLM 自主决策）
- Phase 3: 生成最终报告

关键特性：
1. 代码层管理任务列表，确保按顺序执行
2. 每次调用 LLM 时注入当前任务上下文
3. 任务完成信号 [TASK_DONE] 用于标记单个任务完成
4. 验收环节确认任务真正完成
5. 健壮的循环结束条件
"""
import json
import re
import uuid
import time
from typing import Callable, Dict, Any, Optional, List, Awaitable
from datetime import datetime

from agent.state import AgentState, AgentPhase, Task, TaskStatus
from agent.llm_client import get_llm_client, LLMClient
from tools import tool_read_dataset, tool_run_code, TOOLS_SCHEMA
from prompts import (
    HYBRID_SYSTEM_PROMPT,
    HYBRID_PLANNING_PROMPT,
    HYBRID_TASK_EXECUTION_PROMPT,
    HYBRID_TASK_VERIFICATION_PROMPT,
    HYBRID_REPORT_PROMPT
)
from config.settings import settings
from utils.logger import logger


class HybridAgentLoop:
    """混合模式 Agent（代码控制 + LLM 自主执行）"""
    
    def __init__(
        self,
        dataset_path: str,
        user_request: str,
        event_callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        """
        初始化 Agent
        
        Args:
            dataset_path: 数据集文件路径
            user_request: 用户分析需求
            event_callback: 异步事件回调函数（用于 WebSocket 推送）
        """
        self.dataset_path = dataset_path
        self.user_request = user_request
        self.event_callback = event_callback
        self.llm = get_llm_client()
        self.start_time = None
        
        # 创建 Agent 状态
        self.state = AgentState(
            session_id=str(uuid.uuid4()),
            dataset_path=dataset_path,
            user_request=user_request
        )
        
        # 初始化消息历史
        self.state.messages = [
            {"role": "system", "content": HYBRID_SYSTEM_PROMPT}
        ]
        
        # 任务执行控制
        self.max_iterations_per_task = settings.MAX_ITERATIONS_PER_TASK  # 每个任务最大迭代次数
        self.empty_response_count = 0  # 连续空响应计数
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"[HybridAgent] 初始化")
        logger.info(f"[HybridAgent] Session ID: {self.state.session_id}")
        logger.info(f"[HybridAgent] 数据集: {dataset_path}")
        logger.info(f"[HybridAgent] 用户需求: {user_request[:100]}...")
        logger.info(f"{'#'*60}\n")
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """发送事件"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.state.session_id,
            "payload": payload
        }
        
        logger.info(f"[HybridAgent] 发送事件: type={event_type}")
        await self.event_callback(event)
    
    async def run(self) -> Dict[str, Any]:
        """
        运行混合模式 Agent
        
        Returns:
            最终结果，包含报告和图表
        """
        self.start_time = time.time()
        max_iterations = settings.MAX_ITERATIONS
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[HybridAgent] ===== 开始执行 =====")
        logger.info(f"[HybridAgent] Session: {self.state.session_id}")
        logger.info(f"[HybridAgent] 最大总迭代数: {max_iterations}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request,
                "mode": "hybrid"
            })
            
            # ========== Phase 1: 数据探索 + 任务规划 ==========
            logger.info(f"\n[HybridAgent] ===== Phase 1: 数据探索与任务规划 =====")
            await self.emit_event("phase_change", {"phase": "planning"})
            self.state.phase = AgentPhase.PLANNING
            
            data_info = await self._explore_data()
            await self._plan_tasks(data_info)
            
            # ========== Phase 2: 任务驱动循环 ==========
            logger.info(f"\n[HybridAgent] ===== Phase 2: 任务驱动执行 =====")
            await self.emit_event("phase_change", {"phase": "executing"})
            self.state.phase = AgentPhase.EXECUTING
            
            await self._execute_tasks_loop()
            
            # ========== Phase 3: 生成最终报告 ==========
            logger.info(f"\n[HybridAgent] ===== Phase 3: 生成报告 =====")
            await self.emit_event("phase_change", {"phase": "reporting"})
            self.state.phase = AgentPhase.REPORTING
            
            await self._generate_final_report()
            
            # 完成
            self.state.phase = AgentPhase.COMPLETED
            self.state.completed_at = datetime.utcnow()
            
            total_time = time.time() - self.start_time
            
            logger.info(f"\n{'*'*60}")
            logger.info(f"[HybridAgent] ===== 执行完成 =====")
            logger.info(f"[HybridAgent] 总耗时: {total_time:.2f}秒")
            logger.info(f"[HybridAgent] 总迭代次数: {self.state.iteration}")
            logger.info(f"[HybridAgent] 完成任务数: {len([t for t in self.state.tasks if t.status == TaskStatus.COMPLETED])}/{len(self.state.tasks)}")
            logger.info(f"[HybridAgent] 图表数: {len(self.state.images)}")
            logger.info(f"{'*'*60}\n")
            
            # 发送报告生成事件
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
            logger.error(f"[HybridAgent] ===== 执行失败 =====")
            logger.error(f"[HybridAgent] 错误: {str(e)}")
            logger.error(f"[HybridAgent] 迭代: {self.state.iteration}")
            logger.error(f"[HybridAgent] 耗时: {total_time:.2f}秒")
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
    
    # ==================== Phase 1: 数据探索与任务规划 ====================
    
    async def _explore_data(self) -> Dict[str, Any]:
        """探索数据结构"""
        logger.info(f"[HybridAgent] 开始数据探索...")
        
        await self.emit_event("llm_thinking", {
            "thinking": "正在读取数据集，了解数据结构...",
            "phase": "planning",
            "is_real": True
        })
        
        start = time.time()
        data_info = tool_read_dataset(self.dataset_path, preview_rows=5)
        duration = time.time() - start
        
        if data_info["status"] == "error":
            logger.error(f"[HybridAgent] 数据读取失败: {data_info.get('message')}")
            raise Exception(f"读取数据失败: {data_info.get('message')}")
        
        stats = data_info.get("statistics", {})
        logger.info(f"[HybridAgent] 数据读取完成 (耗时 {duration:.2f}秒)")
        logger.info(f"[HybridAgent]   行数: {stats.get('total_rows', 'N/A')}, 列数: {stats.get('total_columns', 'N/A')}")
        
        await self.emit_event("data_explored", {
            "schema": data_info["schema"],
            "statistics": data_info["statistics"],
            "preview": data_info["preview"][:3]
        })
        
        return data_info
    
    async def _plan_tasks(self, data_info: Dict[str, Any]):
        """规划分析任务（让 LLM 生成 JSON 格式任务清单）"""
        logger.info(f"[HybridAgent] 开始任务规划...")
        
        await self.emit_event("llm_thinking", {
            "thinking": "正在分析用户需求，制定任务清单...",
            "phase": "planning",
            "is_real": True
        })
        
        # 构建数据结构描述
        schema_desc = json.dumps(data_info["schema"], ensure_ascii=False, indent=2)
        stats_desc = json.dumps(data_info["statistics"], ensure_ascii=False, indent=2)
        data_schema = f"列信息:\n{schema_desc}\n\n数据统计:\n{stats_desc}"
        
        # 构建规划提示
        planning_prompt = HYBRID_PLANNING_PROMPT.format(
            user_request=self.user_request,
            data_schema=data_schema
        )
        
        self.state.messages.append({"role": "user", "content": planning_prompt})
        
        # 调用 LLM 生成任务规划（要求 JSON 格式）
        logger.info(f"[HybridAgent] 调用 LLM 进行任务规划...")
        start = time.time()
        response = self.llm.chat_json(self.state.messages)
        duration = time.time() - start
        
        if response["type"] == "error":
            logger.error(f"[HybridAgent] 任务规划失败: {response['error']}")
            raise Exception(f"任务规划失败: {response['error']}")
        
        plan = response["content"]
        tasks_data = plan.get("tasks", [])
        
        logger.info(f"[HybridAgent] LLM 规划完成 (耗时 {duration:.2f}秒)")
        logger.info(f"[HybridAgent] 规划了 {len(tasks_data)} 个任务:")
        
        # 解析任务列表并存储到状态
        for i, task_data in enumerate(tasks_data):
            task = Task(
                id=task_data.get("id", i + 1),
                name=task_data.get("name", f"任务 {i + 1}"),
                description=task_data.get("description", ""),
                type=task_data.get("type", "analysis")
            )
            self.state.tasks.append(task)
            logger.info(f"[HybridAgent]   [{task.id}] {task.name}")
        
        # 记录规划结果到消息历史
        self.state.messages.append({
            "role": "assistant",
            "content": json.dumps(plan, ensure_ascii=False)
        })
        
        await self.emit_event("tasks_planned", {
            "tasks": [t.to_dict() for t in self.state.tasks],
            "analysis_goal": plan.get("analysis_goal", "")
        })
        
        # 发送任务更新事件（用于前端显示）
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
            "source": "planning"
        })
    
    # ==================== Phase 2: 任务驱动循环 ====================
    
    async def _execute_tasks_loop(self):
        """任务驱动循环执行"""
        max_iterations = settings.MAX_ITERATIONS
        
        logger.info(f"[HybridAgent] 开始任务驱动循环")
        logger.info(f"[HybridAgent] 待执行任务数: {len(self.state.tasks)}")
        
        # 按任务循环
        for task in self.state.tasks:
            # 检查是否达到最大迭代数
            if self.state.iteration >= max_iterations:
                logger.warning(f"[HybridAgent] 达到最大迭代数 {max_iterations}，提前终止")
                break
            
            # 执行单个任务
            await self._execute_single_task(task)
        
        # 汇总任务完成情况
        completed = [t for t in self.state.tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in self.state.tasks if t.status == TaskStatus.FAILED]
        
        logger.info(f"[HybridAgent] 任务执行完成: 成功={len(completed)}, 失败={len(failed)}")
    
    async def _execute_single_task(self, task: Task):
        """执行单个任务"""
        task_iterations = 0
        
        # 更新任务状态为进行中
        self.state.current_task_id = task.id
        self.state.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        
        logger.info(f"\n[HybridAgent] ----- 开始任务 [{task.id}]: {task.name} -----")
        
        await self.emit_event("task_started", {
            "task_id": task.id,
            "task_name": task.name,
            "task_description": task.description,
            "iteration": self.state.iteration
        })
        
        # 发送任务状态更新
        await self._emit_tasks_status_update()
        
        task_start_time = time.time()
        
        try:
            # 任务内循环（允许 LLM 多次调用工具完成一个任务）
            while task_iterations < self.max_iterations_per_task:
                self.state.iteration += 1
                task_iterations += 1
                
                logger.info(f"[HybridAgent] 任务 [{task.id}] 迭代 {task_iterations}/{self.max_iterations_per_task} (总迭代 {self.state.iteration})")
                
                # 注入当前任务上下文
                task_prompt = HYBRID_TASK_EXECUTION_PROMPT.format(
                    task_id=task.id,
                    task_name=task.name,
                    task_description=task.description,
                    completed_tasks=self._get_completed_tasks_summary(),
                    dataset_path=self.dataset_path
                )
                
                self.state.messages.append({"role": "user", "content": task_prompt})
                
                # 调用 LLM
                await self.emit_event("llm_thinking", {
                    "thinking": f"正在执行任务 [{task.id}] {task.name}...",
                    "phase": "executing",
                    "task_id": task.id,
                    "is_real": True
                })
                
                response = self.llm.chat(self.state.messages, tools=TOOLS_SCHEMA)
                
                if response["type"] == "error":
                    logger.error(f"[HybridAgent] LLM 调用失败: {response['error']}")
                    raise Exception(f"LLM 调用失败: {response['error']}")
                
                # 处理工具调用
                if response["type"] == "tool_call":
                    tool_result = await self._handle_tool_call(task, response)
                    
                    # 检查工具执行是否成功
                    if tool_result.get("status") == "error":
                        logger.warning(f"[HybridAgent] 工具执行失败，尝试继续...")
                        continue
                    
                    # 工具执行成功后，让 LLM 评估是否完成任务
                    task_done = await self._verify_task_completion(task)
                    
                    if task_done:
                        logger.info(f"[HybridAgent] ✅ 任务 [{task.id}] 已完成")
                        break
                    else:
                        logger.info(f"[HybridAgent] 任务 [{task.id}] 需要继续执行")
                
                else:
                    # LLM 返回文本响应（可能是任务完成的总结）
                    content = response["content"]
                    self.state.messages.append({"role": "assistant", "content": content})
                    
                    # 检查是否声明任务完成
                    if "[TASK_DONE]" in content or self._check_task_done_signal(content):
                        logger.info(f"[HybridAgent] ✅ 任务 [{task.id}] LLM 声明完成")
                        task.result = {"summary": content[:500]}
                        self.state.analysis_results.append({
                            "task_id": task.id,
                            "task_name": task.name,
                            "result": content
                        })
                        break
                    
                    # 发送思考过程
                    await self.emit_event("llm_thinking", {
                        "thinking": content[:300] + ("..." if len(content) > 300 else ""),
                        "phase": "executing",
                        "task_id": task.id,
                        "is_real": True
                    })
            
            # 任务执行完成（正常完成或达到最大迭代数）
            task_duration = time.time() - task_start_time
            
            if task.status != TaskStatus.COMPLETED:
                self.state.update_task_status(task.id, TaskStatus.COMPLETED)
            
            logger.info(f"[HybridAgent] 任务 [{task.id}] 执行完成 (耗时 {task_duration:.2f}秒)")
            
            await self.emit_event("task_completed", {
                "task_id": task.id,
                "task_name": task.name,
                "duration": task_duration
            })
            
            # 更新任务状态显示
            await self._emit_tasks_status_update()
            
        except Exception as e:
            task_duration = time.time() - task_start_time
            logger.error(f"[HybridAgent] ❌ 任务 [{task.id}] 执行失败: {e}")
            
            self.state.update_task_status(task.id, TaskStatus.FAILED, error=str(e))
            
            await self.emit_event("task_failed", {
                "task_id": task.id,
                "task_name": task.name,
                "error": str(e),
                "duration": task_duration
            })
            
            # 更新任务状态显示
            await self._emit_tasks_status_update()
    
    async def _handle_tool_call(self, task: Task, response: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具调用"""
        tool_name = response["name"]
        arguments = response["arguments"]
        tool_call_id = response.get("tool_call_id", f"call_{self.state.iteration}")
        
        logger.info(f"[HybridAgent] 工具调用: {tool_name}")
        
        await self.emit_event("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "task_id": task.id,
            "iteration": self.state.iteration
        })
        
        tool_start = time.time()
        
        # 执行工具
        if tool_name == "read_dataset":
            logger.info(f"[HybridAgent] 执行 read_dataset...")
            result = tool_read_dataset(
                self.dataset_path,
                preview_rows=arguments.get("preview_rows", 5),
                sheet_name=arguments.get("sheet_name")
            )
            
            if result.get("status") == "success":
                await self.emit_event("data_explored", {
                    "schema": result.get("schema", []),
                    "statistics": result.get("statistics", {}),
                    "preview": result.get("preview", [])[:3]
                })
                
        elif tool_name == "run_code":
            code = arguments.get("code", "")
            description = arguments.get("description", "")
            
            logger.info(f"[HybridAgent] 执行 run_code: {description[:50]}...")
            
            # 保存代码到任务
            task.code = code
            
            await self.emit_event("code_generated", {
                "code": code,
                "description": description,
                "task_id": task.id,
                "iteration": self.state.iteration
            })
            
            result = tool_run_code(code, self.dataset_path, description=description)
            
            # 如果有图片，保存并发送
            if result.get("image_base64"):
                logger.info(f"[HybridAgent] 生成了图表")
                self.state.images.append({
                    "task_id": task.id,
                    "task_name": task.name,
                    "iteration": self.state.iteration,
                    "image_base64": result["image_base64"],
                    "description": description
                })
                
                await self.emit_event("image_generated", {
                    "image_base64": result["image_base64"],
                    "task_id": task.id,
                    "iteration": self.state.iteration
                })
        else:
            logger.warning(f"[HybridAgent] 未知工具: {tool_name}")
            result = {"status": "error", "message": f"未知工具: {tool_name}"}
        
        tool_duration = time.time() - tool_start
        
        logger.info(f"[HybridAgent] 工具执行完成 (耗时 {tool_duration:.2f}秒), 状态: {result.get('status')}")
        
        # 构建工具结果摘要
        tool_result_summary = {
            "tool": tool_name,
            "status": result.get("status"),
            "stdout": (result.get("stdout") or "")[:2000],
            "stderr": (result.get("stderr") or "")[:500],
            "has_image": result.get("has_image", False)
        }
        
        # 如果是 read_dataset，添加数据信息
        if tool_name == "read_dataset" and result.get("status") == "success":
            tool_result_summary["schema"] = result.get("schema", [])
            tool_result_summary["statistics"] = result.get("statistics", {})
            tool_result_summary["preview"] = result.get("preview", [])[:5]
        
        await self.emit_event("tool_result", {
            "tool": tool_name,
            "status": result.get("status"),
            "has_image": result.get("has_image", False),
            "stdout_preview": (result.get("stdout") or "")[:300],
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
        
        # 保存任务结果
        task.result = tool_result_summary
        self.state.analysis_results.append({
            "task_id": task.id,
            "task_name": task.name,
            "tool": tool_name,
            "result": tool_result_summary
        })
        
        return result
    
    async def _verify_task_completion(self, task: Task) -> bool:
        """验证任务是否完成"""
        logger.info(f"[HybridAgent] 验证任务 [{task.id}] 完成情况...")
        
        verification_prompt = HYBRID_TASK_VERIFICATION_PROMPT.format(
            task_id=task.id,
            task_name=task.name,
            task_description=task.description
        )
        
        self.state.messages.append({"role": "user", "content": verification_prompt})
        
        # 调用 LLM 进行验收
        response = self.llm.chat(self.state.messages)
        
        if response["type"] == "error":
            logger.warning(f"[HybridAgent] 验收调用失败: {response['error']}")
            return False
        
        content = response["content"]
        self.state.messages.append({"role": "assistant", "content": content})
        
        # 发送验收思考
        await self.emit_event("llm_thinking", {
            "thinking": f"[验收] {content[:200]}...",
            "phase": "verification",
            "task_id": task.id,
            "is_real": True
        })
        
        # 检查完成信号
        is_done = "[TASK_DONE]" in content or self._check_task_done_signal(content)
        
        logger.info(f"[HybridAgent] 任务 [{task.id}] 验收结果: {'完成' if is_done else '未完成'}")
        
        return is_done
    
    def _check_task_done_signal(self, content: str) -> bool:
        """检查内容中是否有任务完成信号"""
        done_signals = [
            "任务完成",
            "已完成",
            "完成了",
            "task done",
            "task completed",
            "finished",
            "分析完成"
        ]
        content_lower = content.lower()
        return any(signal.lower() in content_lower for signal in done_signals)
    
    def _get_completed_tasks_summary(self) -> str:
        """获取已完成任务的摘要"""
        completed = self.state.get_completed_tasks()
        if not completed:
            return "无"
        
        summaries = []
        for t in completed:
            result_summary = ""
            if t.result:
                if isinstance(t.result, dict):
                    result_summary = t.result.get("summary", t.result.get("stdout", ""))[:100]
                else:
                    result_summary = str(t.result)[:100]
            summaries.append(f"- [{t.id}] {t.name}: {result_summary or '完成'}")
        
        return "\n".join(summaries)
    
    async def _emit_tasks_status_update(self):
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
            "source": "execution"
        })
    
    # ==================== Phase 3: 生成最终报告 ====================
    
    async def _generate_final_report(self):
        """生成最终报告"""
        logger.info(f"[HybridAgent] 开始生成最终报告...")
        
        await self.emit_event("llm_thinking", {
            "thinking": "正在汇总所有分析结果，生成最终报告...",
            "phase": "reporting",
            "is_real": True
        })
        
        # 汇总分析结果
        results_summary = json.dumps(
            self.state.analysis_results,
            ensure_ascii=False,
            indent=2
        )
        
        # 任务完成情况
        task_summary = self.state.get_tasks_summary()
        
        # 构建报告生成提示
        report_prompt = HYBRID_REPORT_PROMPT.format(
            user_request=self.user_request,
            task_summary=task_summary,
            analysis_results=results_summary,
            image_count=len(self.state.images)
        )
        
        self.state.messages.append({"role": "user", "content": report_prompt})
        
        # 生成报告
        logger.info(f"[HybridAgent] 调用 LLM 生成报告...")
        start = time.time()
        response = self.llm.chat(self.state.messages)
        duration = time.time() - start
        
        if response["type"] == "error":
            logger.error(f"[HybridAgent] 报告生成失败: {response['error']}")
            self.state.final_report = f"# 分析报告\n\n报告生成失败: {response['error']}\n\n## 原始分析结果\n\n{results_summary}"
        else:
            self.state.final_report = response["content"]
            logger.info(f"[HybridAgent] 报告生成完成 (耗时 {duration:.2f}秒)")
            logger.info(f"[HybridAgent] 报告长度: {len(self.state.final_report)} 字符")
        
        await self.emit_event("llm_thinking", {
            "thinking": f"报告已生成，共 {len(self.state.final_report)} 字符",
            "phase": "reporting",
            "is_real": True,
            "duration": duration
        })
