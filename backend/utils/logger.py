"""
日志模块 - 统一的日志记录
"""
import logging
import sys
from datetime import datetime
from typing import Optional

# 配置日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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


class AgentLogger:
    """Agent 专用日志记录器"""
    
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

