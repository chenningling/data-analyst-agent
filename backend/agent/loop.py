"""
Agent 核心循环模块

实现 LLM 驱动的多轮自主决策循环：
1. Planning - LLM 生成任务清单
2. Execution - LLM 调用工具执行任务
3. Self-evaluation - LLM 评估结果并决定下一步
"""
import json
import uuid
import time
from typing import Callable, Dict, Any, Optional, Awaitable
from datetime import datetime

from agent.state import AgentState, AgentPhase, Task, TaskStatus
from agent.llm_client import get_llm_client, LLMClient
from tools import tool_read_dataset, tool_run_code, TOOLS_SCHEMA
from prompts.system_prompts import (
    AGENT_SYSTEM_PROMPT,
    PLANNING_PROMPT,
    EXECUTION_PROMPT,
    REPORT_GENERATION_PROMPT,
    ERROR_RECOVERY_PROMPT
)
from config.settings import settings
from utils.logger import logger


class AgentLoop:
    """Agent 主循环类（带详细日志）"""
    
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
        self.start_time = None
        
        # 创建 Agent 状态
        self.state = AgentState(
            session_id=str(uuid.uuid4()),
            dataset_path=dataset_path,
            user_request=user_request
        )
        
        # 获取 LLM 客户端并设置 session（每个 session 独立日志文件）
        self.llm = get_llm_client()
        self.llm.set_session(self.state.session_id)
        
        # 初始化消息历史
        self.state.messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT}
        ]
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"[AgentLoop] 初始化")
        logger.info(f"[AgentLoop] Session ID: {self.state.session_id}")
        logger.info(f"[AgentLoop] 数据集: {dataset_path}")
        logger.info(f"[AgentLoop] 用户需求: {user_request[:100]}...")
        logger.info(f"{'#'*60}\n")
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """发送事件（带日志）"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.state.session_id,
            "payload": payload
        }
        
        # 记录发送的事件
        logger.info(f"[AgentLoop] 发送事件: type={event_type}")
        if event_type in ['task_started', 'task_completed', 'task_failed']:
            logger.info(f"[AgentLoop]   任务: id={payload.get('task_id')}, name={payload.get('task_name')}")
        elif event_type == 'tool_call':
            logger.info(f"[AgentLoop]   工具: {payload.get('tool')}")
        elif event_type == 'phase_change':
            logger.info(f"[AgentLoop]   阶段: {payload.get('phase')}")
        
        await self.event_callback(event)
    
    async def run(self) -> Dict[str, Any]:
        """
        运行 Agent 主循环
        
        Returns:
            最终结果，包含报告和图表
        """
        self.start_time = time.time()
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[AgentLoop] ===== 开始执行 Agent =====")
        logger.info(f"[AgentLoop] Session: {self.state.session_id}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request
            })
            
            # 阶段1: 读取数据结构
            logger.info(f"\n[AgentLoop] ===== 阶段 1/4: 数据探索 =====")
            await self.emit_event("phase_change", {"phase": "data_exploration"})
            data_info = await self._explore_data()
            
            # 阶段2: 规划任务
            logger.info(f"\n[AgentLoop] ===== 阶段 2/4: 任务规划 =====")
            await self.emit_event("phase_change", {"phase": "planning"})
            self.state.phase = AgentPhase.PLANNING
            await self._plan_tasks(data_info)
            
            # 阶段3: 执行任务循环
            logger.info(f"\n[AgentLoop] ===== 阶段 3/4: 任务执行 =====")
            await self.emit_event("phase_change", {"phase": "executing"})
            self.state.phase = AgentPhase.EXECUTING
            await self._execute_loop()
            
            # 阶段4: 生成最终报告
            logger.info(f"\n[AgentLoop] ===== 阶段 4/4: 生成报告 =====")
            await self.emit_event("phase_change", {"phase": "reporting"})
            self.state.phase = AgentPhase.REPORTING
            await self._generate_report()
            
            # 完成
            self.state.phase = AgentPhase.COMPLETED
            self.state.completed_at = datetime.utcnow()
            
            total_time = time.time() - self.start_time
            logger.info(f"\n{'*'*60}")
            logger.info(f"[AgentLoop] ===== Agent 执行完成 =====")
            logger.info(f"[AgentLoop] 总耗时: {total_time:.2f}秒")
            logger.info(f"[AgentLoop] 任务数: {len(self.state.tasks)}")
            logger.info(f"[AgentLoop] 图表数: {len(self.state.images)}")
            logger.info(f"[AgentLoop] 迭代次数: {self.state.iteration}")
            logger.info(f"{'*'*60}\n")
            
            await self.emit_event("agent_completed", {
                "final_report": self.state.final_report,
                "images": self.state.images,
                "tasks_summary": self.state.get_tasks_summary()
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
            logger.error(f"[AgentLoop] ===== Agent 执行失败 =====")
            logger.error(f"[AgentLoop] 错误: {str(e)}")
            logger.error(f"[AgentLoop] 阶段: {self.state.phase.value}")
            logger.error(f"[AgentLoop] 耗时: {total_time:.2f}秒")
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
    
    async def _explore_data(self) -> Dict[str, Any]:
        """探索数据结构"""
        logger.info(f"[AgentLoop] 开始数据探索...")
        await self.emit_event("log", {"message": "正在读取数据结构..."})
        
        start = time.time()
        data_info = tool_read_dataset(self.dataset_path, preview_rows=5)
        duration = time.time() - start
        
        if data_info["status"] == "error":
            logger.error(f"[AgentLoop] 数据读取失败: {data_info.get('message')}")
            raise Exception(f"读取数据失败: {data_info.get('message')}")
        
        # 记录数据信息
        stats = data_info.get("statistics", {})
        logger.info(f"[AgentLoop] 数据读取完成 (耗时 {duration:.2f}秒)")
        logger.info(f"[AgentLoop]   行数: {stats.get('total_rows', 'N/A')}")
        logger.info(f"[AgentLoop]   列数: {stats.get('total_columns', 'N/A')}")
        logger.info(f"[AgentLoop]   缺失率: {stats.get('missing_percentage', 'N/A')}%")
        
        schema = data_info.get("schema", [])
        logger.info(f"[AgentLoop]   列名: {[col.get('name') for col in schema[:10]]}...")
        
        await self.emit_event("data_explored", {
            "schema": data_info["schema"],
            "statistics": data_info["statistics"],
            "preview": data_info["preview"][:3]  # 只发送前3行预览
        })
        
        return data_info
    
    async def _plan_tasks(self, data_info: Dict[str, Any]):
        """规划分析任务"""
        logger.info(f"[AgentLoop] 开始任务规划...")
        await self.emit_event("log", {"message": "正在规划分析任务..."})
        
        # 构建数据结构描述
        schema_desc = json.dumps(data_info["schema"], ensure_ascii=False, indent=2)
        stats_desc = json.dumps(data_info["statistics"], ensure_ascii=False, indent=2)
        data_schema = f"列信息:\n{schema_desc}\n\n数据统计:\n{stats_desc}"
        
        # 构建规划提示
        planning_prompt = PLANNING_PROMPT.format(
            user_request=self.user_request,
            data_schema=data_schema
        )
        
        logger.info(f"[AgentLoop] 调用 LLM 进行任务规划...")
        self.state.messages.append({"role": "user", "content": planning_prompt})
        
        # 发送思考过程事件
        await self.emit_event("llm_thinking", {
            "phase": "planning",
            "action": "分析数据结构和用户需求",
            "thinking": f"正在分析数据集结构（{data_info['statistics'].get('total_columns', 0)}列，{data_info['statistics'].get('total_rows', 0)}行）和用户需求，规划分析任务...",
            "input_summary": f"用户需求: {self.user_request[:100]}..."
        })
        
        # 调用 LLM 生成任务规划
        start = time.time()
        response = self.llm.chat_json(self.state.messages)
        duration = time.time() - start
        
        if response["type"] == "error":
            logger.error(f"[AgentLoop] 任务规划失败: {response['error']}")
            raise Exception(f"任务规划失败: {response['error']}")
        
        plan = response["content"]
        
        # 解析任务列表
        tasks_data = plan.get("tasks", [])
        logger.info(f"[AgentLoop] LLM 规划完成 (耗时 {duration:.2f}秒)")
        logger.info(f"[AgentLoop] 规划了 {len(tasks_data)} 个任务:")
        
        # 发送规划结果的思考过程
        task_names = [t.get("name", f"任务{i+1}") for i, t in enumerate(tasks_data)]
        await self.emit_event("llm_thinking", {
            "phase": "planning",
            "action": "任务规划完成",
            "thinking": f"根据用户需求，我制定了 {len(tasks_data)} 个分析任务：{', '.join(task_names)}。分析目标：{plan.get('analysis_goal', '完成数据分析')}",
            "output_summary": f"规划了 {len(tasks_data)} 个任务",
            "duration": duration
        })
        
        for i, task_data in enumerate(tasks_data):
            task = Task(
                id=task_data.get("id", i + 1),
                name=task_data.get("name", f"任务 {i + 1}"),
                description=task_data.get("description", ""),
                type=task_data.get("type", "analysis")
            )
            self.state.tasks.append(task)
            logger.info(f"[AgentLoop]   [{task.id}] {task.name} ({task.type})")
        
        # 记录规划结果
        self.state.messages.append({
            "role": "assistant",
            "content": json.dumps(plan, ensure_ascii=False)
        })
        
        await self.emit_event("tasks_planned", {
            "tasks": [t.to_dict() for t in self.state.tasks],
            "analysis_goal": plan.get("analysis_goal", "")
        })
    
    async def _execute_loop(self):
        """执行任务循环"""
        max_iterations = settings.MAX_ITERATIONS
        
        logger.info(f"[AgentLoop] 开始执行循环 (最大迭代: {max_iterations})")
        
        while self.state.iteration < max_iterations:
            self.state.iteration += 1
            
            # 获取下一个待执行任务
            next_task = self.state.get_next_pending_task()
            
            if not next_task:
                logger.info(f"[AgentLoop] 所有任务已完成，退出循环")
                await self.emit_event("log", {"message": "所有任务已完成"})
                break
            
            # 执行任务
            self.state.current_task_id = next_task.id
            self.state.update_task_status(next_task.id, TaskStatus.IN_PROGRESS)
            
            logger.info(f"\n[AgentLoop] ----- 迭代 {self.state.iteration} -----")
            logger.info(f"[AgentLoop] 开始执行任务 [{next_task.id}]: {next_task.name}")
            logger.info(f"[AgentLoop] 任务描述: {next_task.description[:100]}...")
            
            await self.emit_event("task_started", {
                "task_id": next_task.id,
                "task_name": next_task.name,
                "iteration": self.state.iteration
            })
            
            task_start = time.time()
            
            try:
                await self._execute_task(next_task)
                self.state.update_task_status(next_task.id, TaskStatus.COMPLETED)
                
                task_duration = time.time() - task_start
                logger.info(f"[AgentLoop] ✅ 任务 [{next_task.id}] 完成 (耗时 {task_duration:.2f}秒)")
                
                await self.emit_event("task_completed", {
                    "task_id": next_task.id,
                    "task_name": next_task.name
                })
                
            except Exception as e:
                task_duration = time.time() - task_start
                logger.error(f"[AgentLoop] ❌ 任务 [{next_task.id}] 失败 (耗时 {task_duration:.2f}秒)")
                logger.error(f"[AgentLoop] 错误: {str(e)}")
                
                self.state.update_task_status(
                    next_task.id, 
                    TaskStatus.FAILED, 
                    error=str(e)
                )
                
                await self.emit_event("task_failed", {
                    "task_id": next_task.id,
                    "task_name": next_task.name,
                    "error": str(e)
                })
                
                # 尝试错误恢复
                logger.info(f"[AgentLoop] 尝试错误恢复...")
                if not await self._try_recover(next_task, str(e)):
                    logger.warning(f"[AgentLoop] 错误恢复失败，跳过任务继续")
                    continue  # 跳过失败任务，继续下一个
        
        logger.info(f"[AgentLoop] 执行循环结束，共 {self.state.iteration} 次迭代")
    
    async def _execute_task(self, task: Task):
        """执行单个任务"""
        logger.info(f"[AgentLoop] 准备执行任务...")
        
        # 构建执行提示
        completed_summary = "\n".join([
            f"- {t.name}: {t.result.get('summary', '完成') if t.result else '完成'}"
            for t in self.state.get_completed_tasks()
        ]) or "无"
        
        exec_prompt = EXECUTION_PROMPT.format(
            task_id=task.id,
            task_name=task.name,
            task_description=task.description,
            completed_tasks=completed_summary,
            dataset_path=self.dataset_path
        )
        
        self.state.messages.append({"role": "user", "content": exec_prompt})
        
        # 发送思考过程事件
        await self.emit_event("llm_thinking", {
            "phase": "executing",
            "action": "分析任务需求",
            "thinking": f"正在分析任务 [{task.id}] {task.name}，决定执行策略...",
            "task_id": task.id,
            "task_name": task.name,
            "input_summary": f"任务描述: {task.description[:100]}..."
        })
        
        # 调用 LLM 决定下一步
        logger.info(f"[AgentLoop] 调用 LLM 决策...")
        start_time = time.time()
        response = self.llm.chat(
            self.state.messages,
            tools=TOOLS_SCHEMA
        )
        duration = time.time() - start_time
        
        if response["type"] == "error":
            raise Exception(f"LLM 调用失败: {response['error']}")
        
        # 处理工具调用
        if response["type"] == "tool_call":
            logger.info(f"[AgentLoop] LLM 决定调用工具: {response['name']}")
            
            # 发送决策思考过程
            tool_name = response["name"]
            arguments = response.get("arguments", {})
            
            if tool_name == "run_code":
                thinking_msg = f"我决定编写 Python 代码来完成这个任务。代码将: {arguments.get('description', '执行数据分析')}"
            elif tool_name == "read_dataset":
                thinking_msg = f"我需要先查看数据集的详细信息，以便更好地理解数据结构"
            else:
                thinking_msg = f"我决定调用 {tool_name} 工具"
            
            await self.emit_event("llm_thinking", {
                "phase": "executing",
                "action": "决策",
                "thinking": thinking_msg,
                "decision": f"调用工具: {tool_name}",
                "task_id": task.id,
                "duration": duration
            })
            
            await self._handle_tool_call(task, response)
        else:
            # 普通响应，记录结果
            logger.info(f"[AgentLoop] LLM 返回文本响应")
            content = response["content"]
            self.state.messages.append({"role": "assistant", "content": content})
            
            # 发送思考过程
            await self.emit_event("llm_thinking", {
                "phase": "executing",
                "action": "分析结论",
                "thinking": content[:300] + ("..." if len(content) > 300 else ""),
                "task_id": task.id,
                "duration": duration
            })
            
            task.result = {"summary": content[:500]}
            self.state.analysis_results.append({
                "task_id": task.id,
                "task_name": task.name,
                "result": content
            })
            
            await self.emit_event("log", {
                "message": f"任务 {task.id} 完成",
                "content": content[:200]
            })
    
    async def _handle_tool_call(self, task: Task, response: Dict[str, Any]):
        """处理工具调用"""
        tool_name = response["name"]
        arguments = response["arguments"]
        tool_call_id = response.get("tool_call_id", "")
        
        logger.info(f"[AgentLoop] 处理工具调用: {tool_name}")
        
        await self.emit_event("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "task_id": task.id
        })
        
        tool_start = time.time()
        
        # 执行工具
        if tool_name == "read_dataset":
            logger.info(f"[AgentLoop] 执行 read_dataset...")
            result = tool_read_dataset(
                self.dataset_path,
                preview_rows=arguments.get("preview_rows", 5),
                sheet_name=arguments.get("sheet_name")
            )
        elif tool_name == "run_code":
            code = arguments.get("code", "")
            description = arguments.get("description", "")
            
            logger.info(f"[AgentLoop] 执行 run_code...")
            logger.info(f"[AgentLoop]   描述: {description}")
            logger.info(f"[AgentLoop]   代码长度: {len(code)} 字符")
            
            # 保存代码到任务
            task.code = code
            
            await self.emit_event("code_generated", {
                "task_id": task.id,
                "code": code,
                "description": description
            })
            
            result = tool_run_code(code, self.dataset_path, description=description)
            
            # 如果有图片，保存到状态
            if result.get("image_base64"):
                logger.info(f"[AgentLoop]   生成了图表")
                self.state.images.append({
                    "task_id": task.id,
                    "task_name": task.name,
                    "image_base64": result["image_base64"]
                })
                
                await self.emit_event("image_generated", {
                    "task_id": task.id,
                    "image_base64": result["image_base64"]
                })
        else:
            logger.warning(f"[AgentLoop] 未知工具: {tool_name}")
            result = {"status": "error", "message": f"未知工具: {tool_name}"}
        
        tool_duration = time.time() - tool_start
        
        # 记录工具结果
        logger.info(f"[AgentLoop] 工具执行完成 (耗时 {tool_duration:.2f}秒)")
        logger.info(f"[AgentLoop]   状态: {result.get('status')}")
        
        if result.get("stdout"):
            stdout_preview = result["stdout"][:200].replace('\n', ' ')
            logger.info(f"[AgentLoop]   stdout: {stdout_preview}...")
        
        if result.get("stderr"):
            logger.warning(f"[AgentLoop]   stderr: {result['stderr'][:200]}")
        
        tool_result_summary = {
            "tool": tool_name,
            "status": result.get("status"),
            "stdout": (result.get("stdout") or "")[:1000],
            "stderr": (result.get("stderr") or "")[:500],
            "has_image": result.get("has_image", False)
        }
        
        await self.emit_event("tool_result", {
            "tool": tool_name,
            "status": result.get("status"),
            "has_image": result.get("has_image", False),
            "stdout_preview": (result.get("stdout") or "")[:300]
        })
        
        # 将结果添加到消息历史
        self.state.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments)
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
        
        # 如果执行失败，抛出异常触发重试
        if result.get("status") == "error":
            error_msg = result.get("message") or result.get("stderr") or "代码执行失败"
            logger.error(f"[AgentLoop] 工具执行失败: {error_msg}")
            raise Exception(error_msg)
    
    async def _try_recover(self, task: Task, error: str) -> bool:
        """尝试从错误中恢复"""
        logger.info(f"[AgentLoop] 尝试错误恢复: 任务 {task.id}")
        await self.emit_event("log", {"message": f"尝试修复任务 {task.id} 的错误..."})
        
        if not task.code:
            logger.info(f"[AgentLoop] 无原始代码，无法恢复")
            return False
        
        # 发送错误分析思考过程
        await self.emit_event("llm_thinking", {
            "phase": "error_recovery",
            "action": "分析错误",
            "thinking": f"任务执行出错了，我来分析一下错误原因：{error[:200]}...",
            "task_id": task.id,
            "error": error[:200]
        })
        
        # 构建错误恢复提示
        recovery_prompt = ERROR_RECOVERY_PROMPT.format(
            error_message=error,
            original_code=task.code
        )
        
        self.state.messages.append({"role": "user", "content": recovery_prompt})
        
        # 请求 LLM 修复
        logger.info(f"[AgentLoop] 请求 LLM 修复代码...")
        start_time = time.time()
        response = self.llm.chat(self.state.messages, tools=TOOLS_SCHEMA)
        duration = time.time() - start_time
        
        if response["type"] == "tool_call" and response["name"] == "run_code":
            try:
                # 发送修复思考过程
                await self.emit_event("llm_thinking", {
                    "phase": "error_recovery",
                    "action": "修复代码",
                    "thinking": f"我找到了问题所在，正在修复代码并重新执行...",
                    "task_id": task.id,
                    "duration": duration
                })
                
                logger.info(f"[AgentLoop] LLM 提供了修复代码，执行中...")
                await self._handle_tool_call(task, response)
                self.state.update_task_status(task.id, TaskStatus.COMPLETED)
                logger.info(f"[AgentLoop] ✅ 错误恢复成功!")
                return True
            except Exception as e:
                logger.error(f"[AgentLoop] 错误恢复失败: {e}")
                return False
        
        logger.info(f"[AgentLoop] LLM 未提供修复代码")
        return False
    
    async def _generate_report(self):
        """生成最终报告"""
        logger.info(f"[AgentLoop] 开始生成报告...")
        await self.emit_event("log", {"message": "正在生成最终报告..."})
        
        # 汇总分析结果
        results_summary = json.dumps(
            self.state.analysis_results, 
            ensure_ascii=False, 
            indent=2
        )
        
        logger.info(f"[AgentLoop] 分析结果数量: {len(self.state.analysis_results)}")
        
        # 发送报告生成思考过程
        completed_tasks = [t.name for t in self.state.tasks if t.status == TaskStatus.COMPLETED]
        await self.emit_event("llm_thinking", {
            "phase": "reporting",
            "action": "汇总分析结果",
            "thinking": f"所有分析任务已完成，我将汇总 {len(self.state.analysis_results)} 个分析结果，生成完整的数据分析报告。已完成的任务包括：{', '.join(completed_tasks)}",
            "input_summary": f"分析结果数量: {len(self.state.analysis_results)}, 图表数量: {len(self.state.images)}"
        })
        
        report_prompt = REPORT_GENERATION_PROMPT.format(
            analysis_results=results_summary
        )
        
        self.state.messages.append({"role": "user", "content": report_prompt})
        
        # 生成报告
        logger.info(f"[AgentLoop] 调用 LLM 生成报告...")
        start = time.time()
        response = self.llm.chat(self.state.messages)
        duration = time.time() - start
        
        if response["type"] == "error":
            logger.error(f"[AgentLoop] 报告生成失败: {response['error']}")
            self.state.final_report = f"# 分析报告\n\n报告生成失败: {response['error']}\n\n## 原始分析结果\n\n{results_summary}"
        else:
            self.state.final_report = response["content"]
            logger.info(f"[AgentLoop] 报告生成完成 (耗时 {duration:.2f}秒)")
            logger.info(f"[AgentLoop] 报告长度: {len(self.state.final_report)} 字符")
            
            # 发送报告完成思考过程
            await self.emit_event("llm_thinking", {
                "phase": "reporting",
                "action": "报告生成完成",
                "thinking": f"报告已生成完成，包含数据概览、关键发现、可视化图表和洞察建议等内容。报告长度: {len(self.state.final_report)} 字符",
                "output_summary": f"报告长度: {len(self.state.final_report)} 字符",
                "duration": duration
            })
        
        await self.emit_event("report_generated", {
            "report": self.state.final_report
        })

