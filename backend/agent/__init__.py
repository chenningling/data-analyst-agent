"""
Agent 模块 - 核心 Agent 逻辑

支持三种运行模式：
- staged: 分阶段模式（AgentLoop）- 传统的明确阶段划分
- autonomous: 自主模式（AutonomousAgentLoop）- LLM 完全自主决策
- hybrid: 混合模式（HybridAgentLoop）- 代码控制任务流程 + LLM 自主执行（推荐）
"""
from agent.loop import AgentLoop
from agent.autonomous_loop import AutonomousAgentLoop
from agent.hybrid_loop import HybridAgentLoop
from agent.state import AgentState, TaskStatus

__all__ = [
    "AgentLoop",
    "AutonomousAgentLoop", 
    "HybridAgentLoop",
    "AgentState",
    "TaskStatus"
]

