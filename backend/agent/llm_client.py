"""
LLM 客户端模块 - 封装大模型调用

功能:
- 封装 OpenAI API 调用
- 详细的输入/输出日志记录
- 支持 Function Calling
- 支持流式输出（Streaming）
- 完整的请求/响应 JSON 记录（保存到 record 文件夹）
"""
import json
import os
import time
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Awaitable
from openai import OpenAI, AsyncOpenAI

from config.settings import settings
from utils.logger import logger


class LLMClient:
    """大模型客户端封装（带详细日志，支持流式输出）"""
    
    def __init__(self):
        # 同步客户端（保留兼容性）
        self.client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        # 异步客户端（用于流式输出）
        self.async_client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.model = settings.LLM_MODEL
        self.call_count = 0
        self.current_session_id = None
        
        # 获取项目根目录下的 record 文件夹路径
        self.record_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "record"
        )
        # 确保 record 目录存在
        os.makedirs(self.record_dir, exist_ok=True)
        
        # 默认日志文件路径（会在 set_session 时更新）
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(
            self.record_dir, 
            f"llm_log_{self.session_timestamp}.txt"
        )
        
        logger.info(f"[LLM] 客户端初始化: model={self.model}, base_url={settings.LLM_BASE_URL or 'default'}")
        logger.info(f"[LLM] JSON日志文件: {self.log_file_path}")
        logger.info(f"[LLM] 流式输出: 已启用")
    
    def set_session(self, session_id: str):
        """
        设置当前 session，更新日志文件路径
        
        每个 session 会生成独立的 llm_log 文件
        
        Args:
            session_id: 会话 ID
        """
        self.current_session_id = session_id
        self.call_count = 0  # 重置调用计数
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 使用 session_id 前8位 + 时间戳 作为文件名，方便关联
        short_session_id = session_id[:8] if len(session_id) >= 8 else session_id
        self.log_file_path = os.path.join(
            self.record_dir, 
            f"llm_log_{short_session_id}_{self.session_timestamp}.txt"
        )
        
        logger.info(f"[LLM] 切换 Session: {session_id[:8]}...")
        logger.info(f"[LLM] 新日志文件: {self.log_file_path}")
    
    def _save_json_log(
        self, 
        request_data: Dict[str, Any], 
        response_data: Dict[str, Any], 
        raw_response: Optional[Any] = None,
        duration: float = 0
    ):
        """
        保存请求和响应的完整 JSON 到文件
        
        Args:
            request_data: 发送给大模型的请求数据
            response_data: 处理后的响应数据
            raw_response: 原始 API 响应对象
            duration: 请求耗时
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            log_entry = {
                "call_number": self.call_count,
                "timestamp": timestamp,
                "duration_seconds": round(duration, 3),
                "request": request_data,
                "response": response_data
            }
            
            # 如果有原始响应，尝试提取 usage 信息
            if raw_response and hasattr(raw_response, 'usage') and raw_response.usage:
                log_entry["token_usage"] = {
                    "prompt_tokens": raw_response.usage.prompt_tokens,
                    "completion_tokens": raw_response.usage.completion_tokens,
                    "total_tokens": raw_response.usage.total_tokens
                }
            
            # 追加写入日志文件
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"=== LLM 调用 #{self.call_count} - {timestamp} ===\n")
                f.write(f"{'='*80}\n\n")
                f.write(json.dumps(log_entry, ensure_ascii=False, indent=2))
                f.write(f"\n\n")
            
            logger.debug(f"[LLM] JSON日志已保存: 调用 #{self.call_count}")
            
        except Exception as e:
            logger.warning(f"[LLM] 保存JSON日志失败: {e}")
    
    def _log_request(self, messages: List[Dict[str, Any]], tools: Optional[List] = None, extra_params: dict = None):
        """记录请求日志"""
        self.call_count += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[LLM] ===== 第 {self.call_count} 次调用 =====")
        logger.info(f"[LLM] 模型: {self.model}")
        logger.info(f"[LLM] 消息数量: {len(messages)}")
        
        # 记录最后几条消息（最相关）
        logger.info(f"[LLM] --- 输入消息 ---")
        for i, msg in enumerate(messages[-3:]):  # 只显示最后3条
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            # 截断过长的内容
            if content and len(str(content)) > 500:
                content = str(content)[:500] + "... (截断)"
            
            if msg.get('tool_calls'):
                logger.info(f"[LLM]   [{i}] role={role}, tool_calls={msg['tool_calls']}")
            elif role == 'tool':
                logger.info(f"[LLM]   [{i}] role={role}, tool_call_id={msg.get('tool_call_id')}")
                logger.info(f"[LLM]       内容: {content}")
            else:
                logger.info(f"[LLM]   [{i}] role={role}")
                if content:
                    # 对于长内容，只显示前几行
                    lines = str(content).split('\n')[:5]
                    for line in lines:
                        if line.strip():
                            logger.info(f"[LLM]       {line[:100]}")
        
        if tools:
            tool_names = [t.get('function', {}).get('name', 'unknown') for t in tools]
            logger.info(f"[LLM] 可用工具: {tool_names}")
        
        if extra_params:
            logger.info(f"[LLM] 额外参数: {extra_params}")
    
    def _extract_reasoning(self, message) -> tuple[Optional[str], Optional[str]]:
        """
        从模型响应中提取思考过程和原始字段名
        
        支持多种字段名（不同模型可能使用不同的字段）：
        - reasoning_content: DeepSeek-R1 等模型
        - reasoning: 通用字段名
        - thinking_content: 某些模型
        - thinking: 某些模型
        - reason: 某些模型
        
        Returns:
            (reasoning_value, original_field_name) 元组，如果未找到则返回 (None, None)
        """
        # 可能的思考过程字段名列表
        reasoning_fields = [
            'reasoning_content',
            'reasoning',
            'thinking_content', 
            'thinking',
            'reason',
            'thought',
            'chain_of_thought'
        ]
        
        # 尝试从 message 对象中提取
        for field in reasoning_fields:
            if hasattr(message, field):
                value = getattr(message, field)
                if value:
                    return (str(value), field)
        
        # 尝试从 message 的 __dict__ 中提取（某些模型可能使用动态属性）
        if hasattr(message, '__dict__'):
            for field in reasoning_fields:
                if field in message.__dict__ and message.__dict__[field]:
                    return (str(message.__dict__[field]), field)
        
        # 尝试从 message 作为字典访问（某些 API 可能返回字典）
        if isinstance(message, dict):
            for field in reasoning_fields:
                if field in message and message[field]:
                    return (str(message[field]), field)
        
        return (None, None)
    
    def _log_response(self, response_type: str, result: Dict[str, Any], duration: float):
        """记录响应日志"""
        logger.info(f"[LLM] --- 输出响应 ---")
        logger.info(f"[LLM] 响应类型: {response_type}")
        logger.info(f"[LLM] 耗时: {duration:.2f}秒")
        
        if response_type == "tool_call":
            logger.info(f"[LLM] 工具调用: {result.get('name')}")
            args = result.get('arguments', {})
            # 特殊处理代码参数
            if 'code' in args:
                code_preview = args['code'][:300] + "..." if len(args['code']) > 300 else args['code']
                logger.info(f"[LLM] 参数: description={args.get('description', '')}")
                logger.info(f"[LLM] 代码预览:\n{code_preview}")
            else:
                logger.info(f"[LLM] 参数: {json.dumps(args, ensure_ascii=False)[:500]}")
        
        elif response_type == "response":
            content = result.get('content', '')
            if len(str(content)) > 500:
                logger.info(f"[LLM] 内容预览: {str(content)[:500]}... (截断)")
            else:
                logger.info(f"[LLM] 内容: {content}")
        
        elif response_type == "error":
            logger.error(f"[LLM] 错误: {result.get('error')}")
        
        logger.info(f"{'='*60}\n")
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            tools: 工具定义列表
            temperature: 温度参数
            max_tokens: 最大 token 数
        
        Returns:
            包含响应类型和内容的字典
        """
        # 记录请求
        self._log_request(messages, tools, {"temperature": temperature, "max_tokens": max_tokens})
        
        start_time = time.time()
        
        # 构建请求数据用于日志
        request_data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if tools:
            request_data["tools"] = tools
            request_data["tool_choice"] = "auto"
        
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            response = self.client.chat.completions.create(**kwargs)
            
            duration = time.time() - start_time
            message = response.choices[0].message
            
            # 记录 token 使用情况
            if hasattr(response, 'usage') and response.usage:
                logger.info(f"[LLM] Token 使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")
            
            # 提取模型的思考过程和原始字段名
            reasoning, reasoning_field_name = self._extract_reasoning(message)
            if reasoning:
                logger.info(f"[LLM] 🧠 模型思考过程: {reasoning[:200]}...")
            
            # 构建原始响应数据用于日志（保留原始字段名）
            message_dict = {
                "role": message.role,
                "content": message.content
            }
            # 如果有思考过程，使用原始字段名
            if reasoning and reasoning_field_name:
                message_dict[reasoning_field_name] = reasoning
            
            raw_response_data = {
                "id": response.id if hasattr(response, 'id') else None,
                "model": response.model if hasattr(response, 'model') else None,
                "choices": [{
                    "index": response.choices[0].index if hasattr(response.choices[0], 'index') else 0,
                    "message": message_dict,
                    "finish_reason": response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
                }]
            }
            
            # 如果有工具调用，添加到响应数据
            if message.tool_calls:
                raw_response_data["choices"][0]["message"]["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]
            
            # 检查是否有工具调用
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                result = {
                    "type": "tool_call",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments),
                    "content": message.content or "",  # 保留文本内容
                    "reasoning": reasoning  # 添加思考过程
                }
                self._log_response("tool_call", result, duration)
                
                # 保存 JSON 日志
                self._save_json_log(request_data, raw_response_data, response, duration)
                
                return result
            
            # 普通文本响应
            result = {
                "type": "response",
                "content": message.content or "",
                "reasoning": reasoning  # 添加思考过程
            }
            self._log_response("response", result, duration)
            
            # 保存 JSON 日志
            self._save_json_log(request_data, raw_response_data, response, duration)
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": str(e)
            }
            self._log_response("error", result, duration)
            
            # 保存错误日志
            self._save_json_log(request_data, {"error": str(e), "type": "error"}, None, duration)
            
            return result
    
    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_content_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_reasoning_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_call_start: Optional[Callable[[str], Awaitable[None]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        异步流式聊天请求
        
        支持在生成过程中实时回调，实现打字机效果
        
        Args:
            messages: 消息列表
            tools: 工具定义列表
            on_content_chunk: 内容块回调（每生成一小段文本就调用）
            on_reasoning_chunk: 思考过程块回调（如果模型支持）
            on_tool_call_start: 工具调用开始回调
            temperature: 温度参数
            max_tokens: 最大 token 数
        
        Returns:
            包含响应类型和内容的字典
        """
        # 记录请求
        self._log_request(messages, tools, {"temperature": temperature, "max_tokens": max_tokens, "stream": True})
        
        start_time = time.time()
        
        # 构建请求数据用于日志
        request_data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        if tools:
            request_data["tools"] = tools
            request_data["tool_choice"] = "auto"
        
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            # 使用异步客户端进行流式调用
            stream = await self.async_client.chat.completions.create(**kwargs)
            
            # 收集完整响应
            full_content = ""
            full_reasoning = ""
            reasoning_field_name = None  # 记录原始字段名
            tool_calls_data: Dict[int, Dict[str, Any]] = {}  # index -> {id, name, arguments}
            finish_reason = None
            
            # 处理流式响应
            async for chunk in stream:
                if not chunk.choices:
                    continue
                    
                choice = chunk.choices[0]
                delta = choice.delta
                
                # 记录结束原因
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                
                # 处理思考过程（如果模型支持，如 DeepSeek-R1）
                # 优先使用 reasoning_content（Kimi thinking 模型官方字段）
                reasoning_content = None
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    reasoning_content = delta.reasoning_content
                    if reasoning_field_name is None:
                        reasoning_field_name = 'reasoning_content'
                elif hasattr(delta, 'reasoning') and delta.reasoning:
                    reasoning_content = delta.reasoning
                    if reasoning_field_name is None:
                        reasoning_field_name = 'reasoning'
                
                if reasoning_content:
                    full_reasoning += reasoning_content
                    if on_reasoning_chunk:
                        await on_reasoning_chunk(reasoning_content)
                
                # 处理文本内容
                if delta.content:
                    full_content += delta.content
                    if on_content_chunk:
                        await on_content_chunk(delta.content)
                
                # 处理工具调用（流式中需要拼接）
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": ""
                            }
                        
                        if tc.id:
                            tool_calls_data[idx]["id"] = tc.id
                        
                        if tc.function:
                            if tc.function.name:
                                tool_calls_data[idx]["name"] = tc.function.name
                                # 通知工具调用开始
                                if on_tool_call_start:
                                    await on_tool_call_start(tc.function.name)
                            
                            if tc.function.arguments:
                                tool_calls_data[idx]["arguments"] += tc.function.arguments
            
            duration = time.time() - start_time
            
            # 记录 token 使用（流式模式下可能没有）
            logger.info(f"[LLM] 流式响应完成，耗时: {duration:.2f}秒")
            
            # 构建响应数据用于日志（保留原始字段名）
            message_dict = {
                "role": "assistant",
                "content": full_content
            }
            # 如果有思考过程，使用原始字段名
            if full_reasoning and reasoning_field_name:
                message_dict[reasoning_field_name] = full_reasoning
            
            raw_response_data = {
                "model": self.model,
                "stream": True,
                "choices": [{
                    "message": message_dict,
                    "finish_reason": finish_reason
                }]
            }
            
            # 检查是否有工具调用
            if tool_calls_data:
                # 取第一个工具调用
                first_tool = tool_calls_data[0]
                
                raw_response_data["choices"][0]["message"]["tool_calls"] = [
                    {
                        "id": tc_data["id"],
                        "type": "function",
                        "function": {
                            "name": tc_data["name"],
                            "arguments": tc_data["arguments"]
                        }
                    } for tc_data in tool_calls_data.values()
                ]
                
                try:
                    arguments = json.loads(first_tool["arguments"])
                except json.JSONDecodeError:
                    arguments = {}
                
                result = {
                    "type": "tool_call",
                    "tool_call_id": first_tool["id"],
                    "name": first_tool["name"],
                    "arguments": arguments,
                    "content": full_content,
                    "reasoning": full_reasoning if full_reasoning else None
                }
                
                self._log_response("tool_call", result, duration)
                self._save_json_log(request_data, raw_response_data, None, duration)
                
                return result
            
            # 普通文本响应
            result = {
                "type": "response",
                "content": full_content,
                "reasoning": full_reasoning if full_reasoning else None
            }
            
            self._log_response("response", result, duration)
            self._save_json_log(request_data, raw_response_data, None, duration)
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": str(e)
            }
            self._log_response("error", result, duration)
            self._save_json_log(request_data, {"error": str(e), "type": "error"}, None, duration)
            
            return result
    
    def chat_json(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3
    ) -> Dict[str, Any]:
        """
        发送请求并期望 JSON 响应
        """
        # 记录请求
        self._log_request(messages, None, {"temperature": temperature, "response_format": "json_object"})
        
        start_time = time.time()
        
        # 构建请求数据用于日志
        request_data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"}
            )
            
            duration = time.time() - start_time
            content = response.choices[0].message.content
            
            # 记录 token 使用情况
            if hasattr(response, 'usage') and response.usage:
                logger.info(f"[LLM] Token 使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")
            
            # 构建原始响应数据用于日志
            raw_response_data = {
                "id": response.id if hasattr(response, 'id') else None,
                "model": response.model if hasattr(response, 'model') else None,
                "choices": [{
                    "index": response.choices[0].index if hasattr(response.choices[0], 'index') else 0,
                    "message": {
                        "role": response.choices[0].message.role,
                        "content": content
                    },
                    "finish_reason": response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
                }]
            }
            
            result = {
                "type": "response",
                "content": json.loads(content)
            }
            
            # 记录响应
            logger.info(f"[LLM] --- JSON 响应 ---")
            logger.info(f"[LLM] 耗时: {duration:.2f}秒")
            logger.info(f"[LLM] JSON 内容预览: {json.dumps(result['content'], ensure_ascii=False)[:500]}")
            logger.info(f"{'='*60}\n")
            
            # 保存 JSON 日志
            self._save_json_log(request_data, raw_response_data, response, duration)
            
            return result
            
        except json.JSONDecodeError as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": f"JSON 解析错误: {str(e)}"
            }
            self._log_response("error", result, duration)
            
            # 保存错误日志
            self._save_json_log(request_data, {"error": str(e), "type": "json_decode_error"}, None, duration)
            
            return result
        except Exception as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": str(e)
            }
            self._log_response("error", result, duration)
            
            # 保存错误日志
            self._save_json_log(request_data, {"error": str(e), "type": "error"}, None, duration)
            
            return result


# 全局 LLM 客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client

