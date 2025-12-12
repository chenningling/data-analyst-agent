"""
Agent 状态管理模块
"""
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentPhase(str, Enum):
    """Agent 阶段枚举"""
    INITIALIZING = "initializing"
    PLANNING = "planning"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Task:
    """任务数据类"""
    id: int
    name: str
    description: str
    type: str  # data_exploration, analysis, visualization, report
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    code: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "code": self.code,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


@dataclass
class AgentState:
    """Agent 完整状态"""
    session_id: str
    dataset_path: str
    user_request: str
    phase: AgentPhase = AgentPhase.INITIALIZING
    tasks: List[Task] = field(default_factory=list)
    current_task_id: Optional[int] = None
    iteration: int = 0
    messages: List[Dict[str, Any]] = field(default_factory=list)
    analysis_results: List[Dict[str, Any]] = field(default_factory=list)
    final_report: Optional[str] = None
    images: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """获取指定ID的任务"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def get_current_task(self) -> Optional[Task]:
        """获取当前任务"""
        if self.current_task_id:
            return self.get_task(self.current_task_id)
        return None
    
    def get_next_pending_task(self) -> Optional[Task]:
        """获取下一个待执行的任务"""
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None
    
    def get_completed_tasks(self) -> List[Task]:
        """获取所有已完成的任务"""
        return [t for t in self.tasks if t.status == TaskStatus.COMPLETED]
    
    def all_tasks_completed(self) -> bool:
        """检查是否所有任务都已完成"""
        return all(t.status in [TaskStatus.COMPLETED, TaskStatus.SKIPPED] for t in self.tasks)
    
    def update_task_status(self, task_id: int, status: TaskStatus, result: Any = None, error: str = None):
        """更新任务状态"""
        task = self.get_task(task_id)
        if task:
            task.status = status
            if result:
                task.result = result
            if error:
                task.error = error
            if status == TaskStatus.IN_PROGRESS:
                task.started_at = datetime.utcnow()
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.completed_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_task_id": self.current_task_id,
            "iteration": self.iteration,
            "images_count": len(self.images),
            "has_final_report": self.final_report is not None,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }
    
    def get_tasks_summary(self) -> str:
        """获取任务摘要（用于 LLM）"""
        summary = []
        for task in self.tasks:
            status_icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.IN_PROGRESS: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.SKIPPED: "⏭️"
            }.get(task.status, "❓")
            summary.append(f"{status_icon} [{task.id}] {task.name}: {task.status.value}")
        return "\n".join(summary)

