"""
数据分析 Agent - FastAPI 后端主入口

功能:
- POST /api/start: 上传数据文件 + 分析需求，启动 Agent
- WebSocket /ws: 实时推送 Agent 执行过程
- GET /api/health: 健康检查
"""
import os
import uuid
import tempfile
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent import AgentLoop, AutonomousAgentLoop, HybridAgentLoop, TaskDrivenAgentLoop
from config.settings import settings
from utils.logger import logger, SessionLogger


# 全局会话日志记录器
session_loggers: Dict[str, SessionLogger] = {}


# -------------------
# 事件缓冲管理器（解决时序问题）
# -------------------
class EventBuffer:
    """
    事件缓冲器 - 缓存 WebSocket 连接前的事件，
    确保前端不会丢失任何事件
    """
    
    def __init__(self):
        # session_id -> List[events]
        self.buffers: Dict[str, List[dict]] = defaultdict(list)
        # session_id -> asyncio.Event (等待 WebSocket 连接)
        self.ws_ready_events: Dict[str, asyncio.Event] = {}
        # session_id -> bool (WebSocket 已连接)
        self.ws_connected: Dict[str, bool] = defaultdict(bool)
    
    def create_session(self, session_id: str):
        """创建新会话"""
        self.ws_ready_events[session_id] = asyncio.Event()
        self.ws_connected[session_id] = False
        logger.info(f"[EventBuffer] 创建会话缓冲: session={session_id}")
    
    def add_event(self, session_id: str, event: dict):
        """添加事件到缓冲区"""
        self.buffers[session_id].append(event)
        logger.debug(f"[EventBuffer] 缓存事件: session={session_id}, type={event.get('type')}, 总计={len(self.buffers[session_id])}")
    
    def get_buffered_events(self, session_id: str) -> List[dict]:
        """获取并清空缓冲的事件"""
        events = self.buffers.pop(session_id, [])
        logger.info(f"[EventBuffer] 获取缓存事件: session={session_id}, count={len(events)}")
        return events
    
    def mark_ws_connected(self, session_id: str):
        """标记 WebSocket 已连接"""
        self.ws_connected[session_id] = True
        if session_id in self.ws_ready_events:
            self.ws_ready_events[session_id].set()
        logger.info(f"[EventBuffer] WebSocket 已连接: session={session_id}")
    
    def is_ws_connected(self, session_id: str) -> bool:
        """检查 WebSocket 是否已连接"""
        return self.ws_connected.get(session_id, False)
    
    async def wait_for_ws(self, session_id: str, timeout: float = 10.0) -> bool:
        """等待 WebSocket 连接（带超时）"""
        if session_id not in self.ws_ready_events:
            return False
        try:
            await asyncio.wait_for(
                self.ws_ready_events[session_id].wait(),
                timeout=timeout
            )
            logger.info(f"[EventBuffer] WebSocket 等待完成: session={session_id}")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[EventBuffer] 等待 WebSocket 超时: session={session_id}")
            return False
    
    def cleanup(self, session_id: str):
        """清理会话资源"""
        self.buffers.pop(session_id, None)
        self.ws_ready_events.pop(session_id, None)
        self.ws_connected.pop(session_id, None)
        logger.info(f"[EventBuffer] 清理会话: session={session_id}")


# 全局事件缓冲器
event_buffer = EventBuffer()


# -------------------
# WebSocket 连接管理器
# -------------------
class ConnectionManager:
    """管理 WebSocket 连接"""
    
    def __init__(self):
        # session_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # 广播连接（接收所有事件）
        self.broadcast_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket, session_id: str = None):
        """接受 WebSocket 连接"""
        await websocket.accept()
        
        if session_id:
            if session_id not in self.active_connections:
                self.active_connections[session_id] = []
            self.active_connections[session_id].append(websocket)
            # 标记 WebSocket 已连接
            event_buffer.mark_ws_connected(session_id)
        else:
            self.broadcast_connections.append(websocket)
        
        logger.info(f"WebSocket 连接已建立: session={session_id or 'broadcast'}")
    
    def disconnect(self, websocket: WebSocket, session_id: str = None):
        """断开 WebSocket 连接"""
        if session_id and session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
        
        if websocket in self.broadcast_connections:
            self.broadcast_connections.remove(websocket)
        
        logger.info(f"WebSocket 连接已断开: session={session_id or 'broadcast'}")
    
    async def send_to_session(self, session_id: str, data: dict):
        """向特定 session 发送消息"""
        connections = self.active_connections.get(session_id, []) + self.broadcast_connections
        
        event_type = data.get('type', 'unknown')
        
        # 如果没有活跃连接，先缓存事件
        if not connections:
            event_buffer.add_event(session_id, data)
            logger.info(f"[ConnectionManager] ⚠️ 无活跃连接，事件已缓存: session={session_id[:8]}, type={event_type}")
            return
        
        logger.info(f"[ConnectionManager] 📤 发送事件: session={session_id[:8]}, type={event_type}, connections={len(connections)}")
        
        for connection in connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"[ConnectionManager] 发送 WebSocket 消息失败: {e}")
    
    async def broadcast(self, data: dict):
        """广播消息给所有连接"""
        for connection in self.broadcast_connections:
            try:
                await connection.send_json(data)
            except Exception:
                pass


# 全局连接管理器
manager = ConnectionManager()


# -------------------
# FastAPI 应用
# -------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("数据分析 Agent 服务启动")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    yield
    # 关闭时
    logger.info("数据分析 Agent 服务关闭")


app = FastAPI(
    title="数据分析 Agent API",
    description="基于大模型的自动化数据分析工具",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------
# API 端点
# -------------------
@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0"
    }


@app.post("/api/start")
async def start_analysis(
    file: UploadFile = File(..., description="Excel 或 CSV 数据文件"),
    user_request: str = Form(..., description="分析需求描述")
):
    """
    启动数据分析 Agent
    
    - 上传 Excel/CSV 文件
    - 输入分析需求
    - 返回 session_id，通过 WebSocket 获取实时进度
    """
    # 验证文件类型
    filename = file.filename or "data.xlsx"
    suffix = Path(filename).suffix.lower()
    
    if suffix not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {suffix}。支持: {settings.ALLOWED_EXTENSIONS}"
        )
    
    # 保存上传文件
    session_id = str(uuid.uuid4())
    session_dir = Path(settings.UPLOAD_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    dataset_path = session_dir / filename
    
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件过大")
    
    dataset_path.write_bytes(content)
    logger.info(f"文件已保存: {dataset_path}")
    
    # 创建会话缓冲（关键：在 Agent 启动前创建）
    event_buffer.create_session(session_id)
    
    # 创建会话日志记录器（保存到 record 文件夹）
    session_logger = SessionLogger(session_id, user_request)
    session_loggers[session_id] = session_logger
    session_logger.log(f"文件已上传: {filename}, 大小: {len(content)} 字节")
    
    # 创建事件回调（同时发送 WebSocket 和记录日志）
    async def event_callback(event: dict):
        event_type = event.get('type', 'unknown')
        logger.info(f"[EventCallback] 收到事件: session={session_id[:8]}, type={event_type}")
        
        # 发送 WebSocket
        await manager.send_to_session(session_id, event)
        
        # 记录到日志文件
        if session_id in session_loggers:
            session_loggers[session_id].log_event(event)
    
    # 根据配置选择 Agent 模式
    agent_mode = settings.AGENT_MODE
    logger.info(f"[API] Agent 模式: {agent_mode}")
    
    if agent_mode == "task_driven":
        # 任务驱动模式（推荐）：工具化任务管理 + 任务验收机制
        agent = TaskDrivenAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    elif agent_mode == "hybrid":
        # 混合模式：代码控制任务流程 + LLM 自主执行
        agent = HybridAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    elif agent_mode == "autonomous":
        # 自主循环模式：LLM 完全自主决策
        agent = AutonomousAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    else:
        # 传统分阶段模式
        agent = AgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    
    # 异步运行 Agent（等待 WebSocket 连接后再开始）
    asyncio.create_task(run_agent_with_ws_wait(agent, session_id))
    
    logger.info(f"[API] Agent 任务已创建，等待 WebSocket 连接: session={session_id}")
    
    return JSONResponse({
        "status": "started",
        "session_id": session_id,
        "message": "Agent 已启动，请通过 WebSocket 连接获取实时进度",
        "ws_url": f"/ws/{session_id}"
    })


async def run_agent_with_ws_wait(agent, session_id: str):
    """
    等待 WebSocket 连接后再运行 Agent
    这是解决时序问题的关键函数
    """
    logger.info(f"[Agent] 等待 WebSocket 连接: session={session_id}")
    
    # 等待 WebSocket 连接（最多等待 10 秒）
    ws_connected = await event_buffer.wait_for_ws(session_id, timeout=10.0)
    
    if ws_connected:
        logger.info(f"[Agent] WebSocket 已就绪，开始执行: session={session_id}")
        # 短暂延迟确保前端准备就绪
        await asyncio.sleep(0.2)
    else:
        logger.warning(f"[Agent] WebSocket 等待超时，仍然继续执行: session={session_id}")
    
    # 运行 Agent
    await run_agent_with_error_handling(agent, session_id)


async def run_agent_with_error_handling(agent, session_id: str):
    """带错误处理的 Agent 运行"""
    import time
    start_time = time.time()
    status = "completed"
    
    try:
        logger.info(f"[Agent] 开始执行任务: session={session_id}")
        result = await agent.run()
        status = result.get('status', 'completed')
        logger.info(f"[Agent] 执行完成: session={session_id}, status={status}")
    except Exception as e:
        status = "error"
        logger.error(f"[Agent] 执行失败: session={session_id}, error={e}", exc_info=True)
        await manager.send_to_session(session_id, {
            "type": "error",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {"error": str(e)}
        })
    finally:
        # 完成会话日志记录
        total_duration = time.time() - start_time
        if session_id in session_loggers:
            session_loggers[session_id].finalize(status, total_duration)
            del session_loggers[session_id]
        
        # 清理会话缓冲
        event_buffer.cleanup(session_id)


@app.post("/api/start-sync")
async def start_analysis_sync(
    file: UploadFile = File(...),
    user_request: str = Form(...)
):
    """
    同步方式启动分析（等待完成后返回结果）
    适用于不需要实时进度的场景
    """
    # 验证和保存文件
    filename = file.filename or "data.xlsx"
    suffix = Path(filename).suffix.lower()
    
    if suffix not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")
    
    session_id = str(uuid.uuid4())
    session_dir = Path(settings.UPLOAD_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    dataset_path = session_dir / filename
    dataset_path.write_bytes(await file.read())
    
    # 收集所有事件
    events = []
    
    async def event_callback(event: dict):
        events.append(event)
        await manager.send_to_session(session_id, event)
    
    # 根据配置选择 Agent 模式
    agent_mode = settings.AGENT_MODE
    
    if agent_mode == "task_driven":
        agent = TaskDrivenAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    elif agent_mode == "hybrid":
        agent = HybridAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    elif agent_mode == "autonomous":
        agent = AutonomousAgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    else:
        agent = AgentLoop(
            dataset_path=str(dataset_path),
            user_request=user_request,
            event_callback=event_callback
        )
    
    result = await agent.run()
    
    return JSONResponse({
        **result,
        "events": events
    })


# -------------------
# WebSocket 端点
# -------------------
@app.websocket("/ws/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    """特定 session 的 WebSocket 连接"""
    logger.info(f"[WebSocket] 连接请求: session={session_id}")
    await manager.connect(websocket, session_id)
    logger.info(f"[WebSocket] 已连接: session={session_id}")
    
    try:
        # 发送连接确认
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "payload": {"message": "WebSocket 连接成功"}
        })
        logger.info(f"[WebSocket] 已发送连接确认: session={session_id}")
        
        # 发送缓冲的事件（解决时序问题的关键）
        buffered_events = event_buffer.get_buffered_events(session_id)
        if buffered_events:
            logger.info(f"[WebSocket] 发送缓存事件: session={session_id}, count={len(buffered_events)}")
            for event in buffered_events:
                try:
                    await websocket.send_json(event)
                    logger.debug(f"[WebSocket] 发送缓存事件: type={event.get('type')}")
                except Exception as e:
                    logger.error(f"[WebSocket] 发送缓存事件失败: {e}")
        
        # 保持连接，接收客户端消息
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.WS_HEARTBEAT_INTERVAL
                )
                logger.debug(f"[WebSocket] 收到消息: {data}")
                
                # 处理客户端消息（如心跳）
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
                    
            except asyncio.TimeoutError:
                # 发送心跳
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"[WebSocket] 断开: session={session_id}")
    except Exception as e:
        logger.error(f"[WebSocket] 错误: session={session_id}, error={e}")
    finally:
        manager.disconnect(websocket, session_id)


@app.websocket("/ws")
async def websocket_broadcast(websocket: WebSocket):
    """广播 WebSocket 连接（接收所有 session 的事件）"""
    await manager.connect(websocket)
    
    try:
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "mode": "broadcast"
        })
        
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.WS_HEARTBEAT_INTERVAL
                )
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
                    
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


# -------------------
# 启动入口
# -------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
        log_level="info"
    )

