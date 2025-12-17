"""
配置模块 - 集中管理所有配置项
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """应用配置"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略额外的环境变量
        case_sensitive=False,  # 大小写不敏感
    )
    
    # LLM 配置 - 支持多种环境变量名
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4o", alias="LLM_MODEL")
    
    # Agent 配置
    max_iterations: int = Field(default=25, alias="MAX_ITERATIONS")
    code_timeout: int = Field(default=30, alias="CODE_TIMEOUT")
    max_history_items: int = Field(default=30, alias="MAX_HISTORY_ITEMS")
    # Agent 运行模式：
    # - "tool_driven": 工具驱动模式（推荐）- LLM 完全自主管理任务生命周期
    # - "task_driven": 任务驱动模式 - 代码驱动 + 工具辅助
    # - "hybrid": 混合模式 - 代码控制任务流程 + LLM 自主执行
    # - "autonomous": 自主模式 - LLM 完全自主决策（标签解析）
    # - "staged": 分阶段模式 - 传统的明确阶段划分
    agent_mode: str = Field(default="tool_driven", alias="AGENT_MODE")
    # 每个任务最大迭代次数（仅 hybrid 模式使用）
    max_iterations_per_task: int = Field(default=5, alias="MAX_ITERATIONS_PER_TASK")
    
    # 文件配置
    upload_dir: str = Field(default="/tmp/data_analyst_uploads", alias="UPLOAD_DIR")
    max_file_size: int = Field(default=50 * 1024 * 1024, alias="MAX_FILE_SIZE")
    
    # WebSocket 配置
    ws_heartbeat_interval: int = Field(default=30, alias="WS_HEARTBEAT_INTERVAL")
    
    # 兼容属性
    @property
    def LLM_API_KEY(self) -> str:
        return self.openai_api_key
    
    @property
    def LLM_BASE_URL(self) -> Optional[str]:
        return self.openai_base_url
    
    @property
    def LLM_MODEL(self) -> str:
        return self.llm_model
    
    @property
    def MAX_ITERATIONS(self) -> int:
        return self.max_iterations
    
    @property
    def CODE_TIMEOUT(self) -> int:
        return self.code_timeout
    
    @property
    def UPLOAD_DIR(self) -> str:
        return self.upload_dir
    
    @property
    def ALLOWED_EXTENSIONS(self) -> set:
        return {".xlsx", ".xls", ".csv"}
    
    @property
    def MAX_FILE_SIZE(self) -> int:
        return self.max_file_size
    
    @property
    def WS_HEARTBEAT_INTERVAL(self) -> int:
        return self.ws_heartbeat_interval
    
    @property
    def AGENT_MODE(self) -> str:
        return self.agent_mode
    
    @property
    def MAX_ITERATIONS_PER_TASK(self) -> int:
        return self.max_iterations_per_task


settings = Settings()

