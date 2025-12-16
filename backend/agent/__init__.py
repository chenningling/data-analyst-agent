"""
Agent 模块 - 核心 Agent 逻辑

支持五种运行模式：
- staged: 分阶段模式（AgentLoop）- 传统的明确阶段划分
- autonomous: 自主模式（AutonomousAgentLoop）- LLM 完全自主决策（标签解析）
- hybrid: 混合模式（HybridAgentLoop）- 代码控制任务流程 + LLM 自主执行
- task_driven: 任务驱动模式（TaskDrivenAgentLoop）- 代码驱动 + 工具辅助
- tool_driven: 工具驱动模式（ToolDrivenAgentLoop）- LLM 完全自主管理（推荐）
"""
from agent.loop import AgentLoop
from agent.autonomous_loop import AutonomousAgentLoop
from agent.hybrid_loop import HybridAgentLoop
from agent.task_driven_loop import TaskDrivenAgentLoop
from agent.tool_driven_loop import ToolDrivenAgentLoop
from agent.state import AgentState, TaskStatus

__all__ = [
    "AgentLoop",
    "AutonomousAgentLoop", 
    "HybridAgentLoop",
    "TaskDrivenAgentLoop",
    "ToolDrivenAgentLoop",
    "AgentState",
    "TaskStatus"
]

