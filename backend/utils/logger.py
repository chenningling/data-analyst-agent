"""
日志模块 - 统一的日志记录

功能:
- 控制台日志
- 文件日志（保存到 record 文件夹）
- 会话日志记录器
"""
import logging
import sys
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


# 配置日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# record 目录路径（相对于项目根目录）
RECORD_DIR = Path(__file__).parent.parent.parent / "record"


def setup_logger(
    name: str = "data_analyst",
    level: int = logging.INFO,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    设置并返回 logger
    
    Args:
        name: logger 名称
        level: 日志级别
        log_file: 日志文件路径（可选）
    
    Returns:
        配置好的 logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(console_handler)
    
    # 文件 handler（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(file_handler)
    
    return logger


# 默认 logger
logger = setup_logger()


class SessionLogger:
    """
    会话日志记录器 - 将每次分析会话的完整日志保存到文件
    
    日志文件保存在 record 目录下，格式：
    record/session_{session_id}_{timestamp}.txt
    """
    
    def __init__(self, session_id: str, user_request: str = ""):
        self.session_id = session_id
        self.user_request = user_request
        self.start_time = datetime.now()
        self.events: List[Dict[str, Any]] = []
        self.log_lines: List[str] = []
        
        # 确保 record 目录存在
        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        
        # 生成日志文件名
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_file = RECORD_DIR / f"session_{session_id[:8]}_{timestamp}.txt"
        
        # 写入头部信息
        self._write_header()
        
        logger.info(f"[SessionLogger] 日志文件创建: {self.log_file}")
    
    def _write_header(self):
        """写入日志文件头部"""
        header = [
            "=" * 80,
            f"数据分析 Agent 会话日志",
            "=" * 80,
            f"会话 ID: {self.session_id}",
            f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"用户需求: {self.user_request}",
            "=" * 80,
            "",
        ]
        self.log_lines.extend(header)
        self._flush()
    
    def _flush(self):
        """写入文件"""
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_lines))
        except Exception as e:
            logger.error(f"[SessionLogger] 写入日志文件失败: {e}")
    
    def log(self, message: str, level: str = "INFO"):
        """记录一条日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        self.log_lines.append(line)
        self._flush()
    
    def log_event(self, event: Dict[str, Any]):
        """记录一个事件"""
        self.events.append(event)
        
        event_type = event.get("type", "unknown")
        payload = event.get("payload", {})
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 格式化事件日志
        lines = [
            "",
            f"[{timestamp}] === 事件: {event_type} ===",
        ]
        
        # 根据事件类型格式化内容
        if event_type == "llm_thinking":
            lines.append(f"  阶段: {payload.get('phase', 'N/A')}")
            lines.append(f"  动作: {payload.get('action', 'N/A')}")
            lines.append(f"  思考: {payload.get('thinking', 'N/A')}")
            if payload.get("duration"):
                lines.append(f"  耗时: {payload['duration']:.2f}秒")
        
        elif event_type == "tool_call":
            lines.append(f"  工具: {payload.get('tool', 'N/A')}")
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            args = payload.get("arguments", {})
            if "code" in args:
                lines.append(f"  代码:\n{self._indent(args['code'], 4)}")
            else:
                lines.append(f"  参数: {json.dumps(args, ensure_ascii=False)[:200]}")
        
        elif event_type == "tool_result":
            lines.append(f"  工具: {payload.get('tool', 'N/A')}")
            lines.append(f"  状态: {payload.get('status', 'N/A')}")
            if payload.get("stdout_preview"):
                lines.append(f"  输出: {payload['stdout_preview'][:300]}")
        
        elif event_type == "code_generated":
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            lines.append(f"  描述: {payload.get('description', 'N/A')}")
            if payload.get("code"):
                lines.append(f"  代码:\n{self._indent(payload['code'], 4)}")
        
        elif event_type == "tasks_planned":
            lines.append(f"  目标: {payload.get('analysis_goal', 'N/A')}")
            tasks = payload.get("tasks", [])
            lines.append(f"  任务列表 ({len(tasks)} 个):")
            for task in tasks:
                lines.append(f"    - [{task.get('id')}] {task.get('name')} ({task.get('type')})")
        
        elif event_type == "data_explored":
            stats = payload.get("statistics", {})
            lines.append(f"  行数: {stats.get('total_rows', 'N/A')}")
            lines.append(f"  列数: {stats.get('total_columns', 'N/A')}")
            lines.append(f"  缺失率: {stats.get('missing_percentage', 'N/A')}%")
        
        elif event_type == "task_started":
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            lines.append(f"  任务名: {payload.get('task_name', 'N/A')}")
        
        elif event_type == "task_completed":
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            lines.append(f"  任务名: {payload.get('task_name', 'N/A')}")
        
        elif event_type == "task_failed":
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            lines.append(f"  任务名: {payload.get('task_name', 'N/A')}")
            lines.append(f"  错误: {payload.get('error', 'N/A')}")
        
        elif event_type == "report_generated":
            report = payload.get("report", "")
            lines.append(f"  报告长度: {len(report)} 字符")
            lines.append(f"  报告预览:\n{self._indent(report[:500], 4)}...")
        
        elif event_type == "agent_completed":
            lines.append(f"  最终报告长度: {len(payload.get('final_report', ''))} 字符")
            lines.append(f"  图表数量: {len(payload.get('images', []))}")
        
        elif event_type == "agent_error":
            lines.append(f"  错误: {payload.get('error', 'N/A')}")
        
        elif event_type == "phase_change":
            lines.append(f"  新阶段: {payload.get('phase', 'N/A')}")
        
        elif event_type == "image_generated":
            lines.append(f"  任务ID: {payload.get('task_id', 'N/A')}")
            lines.append(f"  [图片已生成]")
        
        else:
            lines.append(f"  Payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
        
        self.log_lines.extend(lines)
        self._flush()
    
    def _indent(self, text: str, spaces: int) -> str:
        """缩进文本"""
        indent = " " * spaces
        return "\n".join(indent + line for line in text.split("\n"))
    
    def log_llm_call(self, call_number: int, messages_count: int, response_type: str, 
                      duration: float, content_preview: str = ""):
        """记录 LLM 调用"""
        lines = [
            "",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] === LLM 调用 #{call_number} ===",
            f"  消息数量: {messages_count}",
            f"  响应类型: {response_type}",
            f"  耗时: {duration:.2f}秒",
        ]
        if content_preview:
            lines.append(f"  响应预览: {content_preview[:200]}...")
        
        self.log_lines.extend(lines)
        self._flush()
    
    def finalize(self, status: str = "completed", total_duration: float = 0):
        """完成日志记录"""
        footer = [
            "",
            "=" * 80,
            f"会话结束",
            "=" * 80,
            f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"总耗时: {total_duration:.2f}秒",
            f"最终状态: {status}",
            f"事件总数: {len(self.events)}",
            "=" * 80,
        ]
        self.log_lines.extend(footer)
        self._flush()
        
        logger.info(f"[SessionLogger] 日志已保存: {self.log_file}")
        return str(self.log_file)


class AgentLogger:
    """Agent 专用日志记录器（旧版兼容）"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.logger = setup_logger(f"agent.{session_id[:8]}")
        self.events = []
    
    def log(self, level: str, message: str, **kwargs):
        """记录日志"""
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "level": level,
            "message": message,
            **kwargs
        }
        self.events.append(event)
        
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        log_func(f"[{self.session_id[:8]}] {message}")
        
        return event
    
    def info(self, message: str, **kwargs):
        return self.log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        return self.log("WARNING", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        return self.log("ERROR", message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        return self.log("DEBUG", message, **kwargs)
    
    def get_events(self):
        """获取所有事件"""
        return self.events
