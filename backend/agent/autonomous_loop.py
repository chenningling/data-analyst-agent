"""
自主循环 Agent 模块

实现 LLM 自主决策循环：
- 只发送一条 user 消息（初始请求）
- LLM 自主决定每一步操作
- 解析 <thinking> 和 <tasks> 标签
- 直到检测到 [ANALYSIS_COMPLETE] 结束
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
from prompts import AUTONOMOUS_AGENT_PROMPT
from config.settings import settings
from utils.logger import logger


class AutonomousAgentLoop:
    """自主循环 Agent（LLM 自主决策）"""
    
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
        
        # 初始化消息历史 - 只有 system 提示词
        self.state.messages = [
            {"role": "system", "content": AUTONOMOUS_AGENT_PROMPT}
        ]
        
        # 记录思考历史
        self.thinking_history: List[str] = []
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"[AutonomousAgent] 初始化")
        logger.info(f"[AutonomousAgent] Session ID: {self.state.session_id}")
        logger.info(f"[AutonomousAgent] 数据集: {dataset_path}")
        logger.info(f"[AutonomousAgent] 用户需求: {user_request[:100]}...")
        logger.info(f"{'#'*60}\n")
    
    async def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """发送事件"""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.state.session_id,
            "payload": payload
        }
        
        logger.info(f"[AutonomousAgent] 发送事件: type={event_type}")
        await self.event_callback(event)
    
    def _extract_thinking(self, content: str) -> Optional[str]:
        """从 LLM 输出中提取思考过程"""
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
        match = re.search(r'<tasks>(.*?)</tasks>', content, re.DOTALL)
        if not match:
            return None
        
        tasks_content = match.group(1).strip()
        tasks = []
        
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
                task_name = re.sub(r'[（(].*?[)）]', '', task_name).strip()
                
                tasks.append({
                    "id": i + 1,
                    "name": task_name,
                    "status": "completed" if is_completed else "pending",
                    "description": "",
                    "type": "analysis"
                })
        
        return tasks if tasks else None
    
    def _is_analysis_complete(self, content: str) -> bool:
        """检查分析是否完成"""
        return "[ANALYSIS_COMPLETE]" in content
    
    def _extract_report(self, content: str) -> str:
        """提取最终报告内容"""
        # 移除 <thinking> 和 <tasks> 标签
        report = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL)
        report = re.sub(r'<tasks>.*?</tasks>', '', report, flags=re.DOTALL)
        # 移除结束标记
        report = report.replace('[ANALYSIS_COMPLETE]', '').strip()
        # 移除末尾的分隔线
        report = re.sub(r'\n---\s*$', '', report)
        return report.strip()
    
    async def run(self) -> Dict[str, Any]:
        """
        运行自主循环 Agent
        
        Returns:
            最终结果，包含报告和图表
        """
        self.start_time = time.time()
        max_iterations = settings.MAX_ITERATIONS
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"[AutonomousAgent] ===== 开始执行 =====")
        logger.info(f"[AutonomousAgent] Session: {self.state.session_id}")
        logger.info(f"[AutonomousAgent] 最大迭代次数: {max_iterations}")
        logger.info(f"{'*'*60}\n")
        
        try:
            await self.emit_event("agent_started", {
                "session_id": self.state.session_id,
                "user_request": self.user_request,
                "mode": "autonomous"
            })
            
            # 添加唯一的 user 消息（初始请求）
            initial_message = f"""请分析以下数据集：

## 数据文件路径
{self.dataset_path}

## 用户分析需求
{self.user_request}

请开始执行分析，记得每次回复都要包含 <thinking> 和 <tasks> 标签。"""
            
            self.state.messages.append({"role": "user", "content": initial_message})
            
            await self.emit_event("phase_change", {"phase": "autonomous_running"})
            self.state.phase = AgentPhase.EXECUTING
            
            # 自主循环
            while self.state.iteration < max_iterations:
                self.state.iteration += 1
                
                logger.info(f"\n[AutonomousAgent] ----- 迭代 {self.state.iteration}/{max_iterations} -----")
                
                iteration_start = time.time()
                
                # 调用 LLM
                response = self.llm.chat(
                    self.state.messages,
                    tools=TOOLS_SCHEMA
                )
                
                iteration_duration = time.time() - iteration_start
                
                if response["type"] == "error":
                    logger.error(f"[AutonomousAgent] LLM 调用失败: {response['error']}")
                    await self.emit_event("agent_error", {"error": response["error"]})
                    raise Exception(f"LLM 调用失败: {response['error']}")
                
                if response["type"] == "tool_call":
                    # 处理工具调用（可能包含文本内容）
                    await self._handle_tool_call(response, iteration_duration)
                    
                elif response["type"] == "response":
                    # 处理文本响应
                    content = response["content"]
                    
                    # 添加到消息历史
                    self.state.messages.append({"role": "assistant", "content": content})
                    
                    # 解析并发送思考过程
                    thinking = self._extract_thinking(content)
                    if thinking:
                        self.thinking_history.append(thinking)
                        await self.emit_event("llm_thinking", {
                            "thinking": thinking,
                            "is_real": True,
                            "iteration": self.state.iteration,
                            "duration": iteration_duration
                        })
                        logger.info(f"[AutonomousAgent] 思考: {thinking[:100]}...")
                    
                    # 解析并发送任务状态
                    tasks = self._extract_tasks(content)
                    if tasks:
                        # 更新内部状态
                        self.state.tasks = [
                            Task(
                                id=t["id"],
                                name=t["name"],
                                description=t.get("description", ""),
                                type=t.get("type", "analysis"),
                                status=TaskStatus.COMPLETED if t["status"] == "completed" else TaskStatus.PENDING
                            )
                            for t in tasks
                        ]
                        
                        await self.emit_event("tasks_updated", {
                            "tasks": tasks,
                            "source": "llm"
                        })
                        logger.info(f"[AutonomousAgent] 任务更新: {[t['name'] for t in tasks]}")
                    
                    # 检查是否完成
                    if self._is_analysis_complete(content):
                        logger.info(f"[AutonomousAgent] ✅ 检测到分析完成标记")
                        self.state.final_report = self._extract_report(content)
                        break
                    
                    # 发送日志事件
                    await self.emit_event("log", {
                        "message": f"迭代 {self.state.iteration} 完成",
                        "iteration": self.state.iteration
                    })
            
            # 完成
            self.state.phase = AgentPhase.COMPLETED
            self.state.completed_at = datetime.utcnow()
            
            total_time = time.time() - self.start_time
            
            logger.info(f"\n{'*'*60}")
            logger.info(f"[AutonomousAgent] ===== 执行完成 =====")
            logger.info(f"[AutonomousAgent] 总耗时: {total_time:.2f}秒")
            logger.info(f"[AutonomousAgent] 迭代次数: {self.state.iteration}")
            logger.info(f"[AutonomousAgent] 图表数: {len(self.state.images)}")
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
            logger.error(f"[AutonomousAgent] ===== 执行失败 =====")
            logger.error(f"[AutonomousAgent] 错误: {str(e)}")
            logger.error(f"[AutonomousAgent] 迭代: {self.state.iteration}")
            logger.error(f"[AutonomousAgent] 耗时: {total_time:.2f}秒")
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
    
    async def _handle_tool_call(self, response: Dict[str, Any], iteration_duration: float = 0):
        """处理工具调用"""
        tool_name = response["name"]
        arguments = response["arguments"]
        tool_call_id = response.get("tool_call_id", f"call_{self.state.iteration}")
        content = response.get("content", "")  # LLM 可能同时输出文本
        
        logger.info(f"[AutonomousAgent] 工具调用: {tool_name}")
        
        # 尝试从 content 中解析思考过程和任务状态
        if content:
            thinking = self._extract_thinking(content)
            tasks = self._extract_tasks(content)
            
            if thinking:
                self.thinking_history.append(thinking)
                await self.emit_event("llm_thinking", {
                    "thinking": thinking,
                    "is_real": True,
                    "iteration": self.state.iteration,
                    "duration": iteration_duration
                })
                logger.info(f"[AutonomousAgent] 思考: {thinking[:100]}...")
            
            if tasks:
                self.state.tasks = [
                    Task(
                        id=t["id"],
                        name=t["name"],
                        description=t.get("description", ""),
                        type=t.get("type", "analysis"),
                        status=TaskStatus.COMPLETED if t["status"] == "completed" else TaskStatus.PENDING
                    )
                    for t in tasks
                ]
                await self.emit_event("tasks_updated", {
                    "tasks": tasks,
                    "source": "llm"
                })
        
        # 如果没有思考内容，生成一个简单的描述
        if not content or not self._extract_thinking(content):
            tool_desc = {
                "read_dataset": "读取数据结构",
                "run_code": arguments.get("description", "执行代码分析")
            }
            simple_thinking = f"调用 {tool_name} → {tool_desc.get(tool_name, '执行操作')}"
            
            await self.emit_event("llm_thinking", {
                "thinking": simple_thinking,
                "is_real": False,  # 标记为系统生成
                "iteration": self.state.iteration,
                "tool": tool_name
            })
            logger.info(f"[AutonomousAgent] (系统生成) 思考: {simple_thinking}")
        
        await self.emit_event("tool_call", {
            "tool": tool_name,
            "arguments": arguments,
            "iteration": self.state.iteration
        })
        
        tool_start = time.time()
        
        # 执行工具
        if tool_name == "read_dataset":
            logger.info(f"[AutonomousAgent] 执行 read_dataset...")
            result = tool_read_dataset(
                self.dataset_path,
                preview_rows=arguments.get("preview_rows", 5),
                sheet_name=arguments.get("sheet_name")
            )
            
            # 发送数据探索事件
            if result.get("status") == "success":
                await self.emit_event("data_explored", {
                    "schema": result.get("schema", []),
                    "statistics": result.get("statistics", {}),
                    "preview": result.get("preview", [])[:3]
                })
                
        elif tool_name == "run_code":
            code = arguments.get("code", "")
            description = arguments.get("description", "")
            
            logger.info(f"[AutonomousAgent] 执行 run_code: {description[:50]}...")
            
            await self.emit_event("code_generated", {
                "code": code,
                "description": description,
                "iteration": self.state.iteration
            })
            
            result = tool_run_code(code, self.dataset_path, description=description)
            
            # 如果有图片，保存并发送
            if result.get("image_base64"):
                logger.info(f"[AutonomousAgent] 生成了图表")
                self.state.images.append({
                    "iteration": self.state.iteration,
                    "image_base64": result["image_base64"],
                    "description": description
                })
                
                await self.emit_event("image_generated", {
                    "image_base64": result["image_base64"],
                    "iteration": self.state.iteration
                })
        else:
            logger.warning(f"[AutonomousAgent] 未知工具: {tool_name}")
            result = {"status": "error", "message": f"未知工具: {tool_name}"}
        
        tool_duration = time.time() - tool_start
        
        logger.info(f"[AutonomousAgent] 工具执行完成 (耗时 {tool_duration:.2f}秒), 状态: {result.get('status')}")
        
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


