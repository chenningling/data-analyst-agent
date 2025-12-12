"""
LLM 客户端模块 - 封装大模型调用

功能:
- 封装 OpenAI API 调用
- 详细的输入/输出日志记录
- 支持 Function Calling
"""
import json
import os
import time
from typing import List, Dict, Any, Optional
from openai import OpenAI

from config.settings import settings
from utils.logger import logger


class LLMClient:
    """大模型客户端封装（带详细日志）"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.model = settings.LLM_MODEL
        self.call_count = 0
        
        logger.info(f"[LLM] 客户端初始化: model={self.model}, base_url={settings.LLM_BASE_URL or 'default'}")
    
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
            
            # 检查是否有工具调用
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                result = {
                    "type": "tool_call",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                }
                self._log_response("tool_call", result, duration)
                return result
            
            # 普通文本响应
            result = {
                "type": "response",
                "content": message.content or ""
            }
            self._log_response("response", result, duration)
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": str(e)
            }
            self._log_response("error", result, duration)
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
            
            result = {
                "type": "response",
                "content": json.loads(content)
            }
            
            # 记录响应
            logger.info(f"[LLM] --- JSON 响应 ---")
            logger.info(f"[LLM] 耗时: {duration:.2f}秒")
            logger.info(f"[LLM] JSON 内容预览: {json.dumps(result['content'], ensure_ascii=False)[:500]}")
            logger.info(f"{'='*60}\n")
            
            return result
            
        except json.JSONDecodeError as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": f"JSON 解析错误: {str(e)}"
            }
            self._log_response("error", result, duration)
            return result
        except Exception as e:
            duration = time.time() - start_time
            result = {
                "type": "error",
                "error": str(e)
            }
            self._log_response("error", result, duration)
            return result


# 全局 LLM 客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client

