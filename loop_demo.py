"""
main.py

基于 FastAPI 的最小可行数据分析 Agent Demo。

功能:
- POST /start : 上传 Excel + 输入分析需求 → 启动 Agent（同步调用，直接执行循环）
- WebSocket /ws : 前端连接以接收实时事件（任务列表、日志、最终报告）
- Agent 循环：通过函数调用形式使用大模型（你需要集成自己的 LLM Client）
- 两个可用工具:
    - read_dataset(preview_rows)
    - execute_python_code(code)  --> 在子进程中执行代码，捕获 stdout/stderr，并可返回图片

运行方式:
    pip install fastapi uvicorn pandas openpyxl python-multipart
    # 安装你的 LLM 客户端库 / openai（如需要）
    uvicorn main:app --reload --port 8003
"""

import os
import json
import tempfile
import base64
import subprocess
import traceback
from typing import Callable, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import asyncio
from pathlib import Path
from datetime import datetime

app = FastAPI()

# -------------------
# 配置
# -------------------
# 你需要在此替换成真实的大模型客户端初始化。
# 示例: openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# 下面的 call_model 是你需要实现的薄封装。
LLM_MODEL_NAME = "gpt-4o"  # 仅用于参考


# -------------------
# WebSocket 管理器（简单版本）
# -------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast_json(self, data: dict):
        for ws in list(self.active_connections):
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


# -------------------
# 工具：安全执行子进程代码
# -------------------
def run_user_code_in_subprocess(code: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """
    在一个单独的 Python 子进程中执行用户代码，并带超时限制。
    代码被写入临时文件后执行。约定：
      - 如果代码要返回结构化数据，需要写一个名为 "result.json" 的文件
      - 如果代码要返回图像，应保存为 "result.png"
    返回:
      {"status": "success"/"error", "stdout": "...", "stderr": "...",
       "result_json": {...} 或 None, "image_base64": "..." 或 None}

    重要安全提示:
        这是一个 Demo。子进程依然可以访问网络/文件系统。
        生产环境必须运行在隔离沙箱、禁止网络、限制资源。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "script.py"
        result_json_path = Path(tmpdir) / "result.json"
        result_png_path = Path(tmpdir) / "result.png"

        # 包装用户代码，以确保 stdout/stderr 能捕获
        wrapper = f"""
import traceback, json, os
try:
{code}
except Exception as e:
    print('---__EXCEPTION_START__---')
    traceback.print_exc()
    print('---__EXCEPTION_END__---')
"""

        script_path.write_text(wrapper, encoding="utf-8")

        try:
            proc = subprocess.run(
                ["python", str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            result_json = None
            image_b64 = None

            if result_json_path.exists():
                try:
                    result_json = json.loads(result_json_path.read_text(encoding="utf-8"))
                except Exception:
                    result_json = {"error": "malformed result.json"}

            if result_png_path.exists():
                image_b64 = base64.b64encode(result_png_path.read_bytes()).decode("utf-8")

            return {
                "status": "success",
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "result_json": result_json,
                "image_base64": image_b64
            }

        except subprocess.TimeoutExpired as te:
            return {"status": "error", "message": f"timeout after {timeout_seconds}s", "stdout": te.stdout, "stderr": te.stderr}
        except Exception as e:
            return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


# -------------------
# 工具（暴露给大模型）
# -------------------
def tool_read_dataset(dataset_path: str, preview_rows: int = 5) -> Dict[str, Any]:
    try:
        df = pd.read_excel(dataset_path)
        preview = df.head(preview_rows).to_dict(orient="records")
        schema = [{"column": c, "dtype": str(df[c].dtype)} for c in df.columns]
        return {"status": "success", "preview": preview, "schema": schema, "rows": len(df)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_execute_python_code(code: str) -> Dict[str, Any]:
    """
    在子进程中执行 Python 代码。
    用户代码可:
      - 创建 'result.png' 保存图表
      - 创建 'result.json' 保存结构化结果

    示例代码:
        import pandas as pd, matplotlib.pyplot as plt, json
        df = pd.read_excel('uploaded.xlsx')
        res = df.describe().to_dict()
        plt.figure(); df['col'].hist(); plt.savefig('result.png')
        with open('result.json','w') as f: json.dump(res, f)
    """
    return run_user_code_in_subprocess(code, timeout_seconds=12)


# -------------------
# 大模型集成占位
# -------------------
def call_model(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    调用大模型的最小占位函数（你必须替换为真实的 LLM 调用）。

    参数:
        - messages: [{"role": "system|user|assistant|tool", "content": "..."}]
        - tools: 工具描述（函数调用规范）

    返回字典:
        - "type": "response" 或 "tool_call"
        - 若 type=response → {"content": "..."}
        - 若 type=tool_call → {"name": "工具名", "arguments": {...}}

    TODO: 替换成真实 LLM SDK 的函数调用。

    下方是为了调试而写的模拟逻辑（极简 planner + 工具调用）。
    """

    # 非常 naive 的 mock，用关键字判断行为

    # 若用户要求规划任务
    if any("规划任务清单" in (m.get("content") or "") or "请根据以下需求规划任务清单" in (m.get("content") or "") for m in messages):
        plan = {
            "tasks": [
                {"id": 1, "desc": "预览数据（5行）", "status": "pending"},
                {"id": 2, "desc": "计算描述统计并画图", "status": "pending"},
                {"id": 3, "desc": "写分析结论", "status": "pending"}
            ]
        }
        return {"type": "response", "content": json.dumps(plan, ensure_ascii=False)}

    # 若模型看到当前任务状态，决定调用工具
    last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
    if last_user and "当前任务状态" in (last_user.get("content") or ""):
        state = last_user["content"]
        if '"status": "pending"' in state:
            return {"type": "tool_call", "name": "read_dataset", "arguments": {"preview_rows": 5}}
        else:
            return {"type": "response", "content": "最终分析：数据已处理，见图表与结论。"}

    return {"type": "response", "content": "我不确定下一步，该任务需要人工干预。"}


# -------------------
# Agent 实现（MVP）
# -------------------
SYSTEM_PROMPT = (
    "你是一名数据分析 Agent。你必须规划任务、选择性调用工具，并生成最终分析报告。"
)

MAX_HISTORY_ITEMS = 30  # LLM 历史消息滑动窗口


class Agent:
    def __init__(self, dataset_path: str, user_request: str, ws_broadcast: Callable[[dict], Any]):
        self.dataset_path = dataset_path
        self.user_request = user_request
        self.ws_broadcast = ws_broadcast

        self.messages: List[Dict[str, Any]] = []
        self.tasks: List[Dict[str, Any]] = []

        # 工具描述（供真实大模型 function-calling 使用）
        self.tools_schema = [
            {
                "name": "read_dataset",
                "description": "读取上传的数据集，返回预览和 schema。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "preview_rows": {"type": "number"}
                    },
                    "required": ["preview_rows"]
                }
            },
            {
                "name": "execute_python_code",
                "description": "执行分析用的 Python 代码；可返回 result.json 或 result.png。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"}
                    },
                    "required": ["code"]
                }
            },
        ]

    async def send_event(self, event_type: str, payload: dict):
        payload_with_ts = {"ts": datetime.utcnow().isoformat() + "Z", "type": event_type, "payload": payload}
        await self.ws_broadcast(payload_with_ts)

    def append_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

        # 限制历史消息长度
        if len(self.messages) > MAX_HISTORY_ITEMS:
            self.messages = [self.messages[0], self.messages[1]] + self.messages[-(MAX_HISTORY_ITEMS - 2):]

    async def plan_tasks(self):
        # 初始化对话
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请根据以下需求规划任务清单：{self.user_request}"}
        ]
        resp = call_model(self.messages, tools=self.tools_schema)
        if resp["type"] == "response":
            try:
                plan = json.loads(resp["content"])
                self.tasks = plan.get("tasks", [])
            except Exception:
                self.tasks = [{"id": 1, "desc": "分析并返回结果", "status": "pending"}]
        else:
            self.tasks = [{"id": 1, "desc": "分析并返回结果", "status": "pending"}]

        await self.send_event("task_list", {"tasks": self.tasks})
        self.append_message("assistant", json.dumps({"tasks": self.tasks}, ensure_ascii=False))

    async def run_loop(self):
        """
        Agent 主循环:
            - 告诉 LLM 当前任务状态
            - LLM 要么调用工具，要么给最终结论
            - 如果调用工具 → 执行 → 结果回传给 LLM
            - 循环直到 LLM 结束
        """
        # 1) 规划任务
        await self.plan_tasks()

        max_iterations = 20
        it = 0

        while it < max_iterations:
            it += 1

            task_state = json.dumps(self.tasks, ensure_ascii=False)
            self.append_message("user", f"当前任务状态：{task_state}\n请给出下一步（或者调用工具）")
            await self.send_event("log", {"msg": f"询问模型下一步（迭代 {it}）", "task_state": self.tasks})

            llm_resp = call_model(self.messages, tools=self.tools_schema)

            # --- 工具调用 ---
            if llm_resp["type"] == "tool_call":
                name = llm_resp["name"]
                args = llm_resp.get("arguments", {})

                await self.send_event("log", {"msg": f"模型请求工具: {name}", "args": args})

                if name == "read_dataset":
                    result = tool_read_dataset(self.dataset_path, preview_rows=args.get("preview_rows", 5))
                elif name == "execute_python_code":
                    code = args.get("code", "")
                    result = tool_execute_python_code(code)
                else:
                    result = {"status": "error", "message": f"unknown tool {name}"}

                short_summary = {
                    "tool": name,
                    "status": result.get("status"),
                    "message": result.get("message", "")[:200]
                }
                if result.get("image_base64"):
                    short_summary["has_image"] = True
                    short_summary["image_base64_truncated"] = (result["image_base64"][:300] + "...")

                await self.send_event("tool_result", short_summary)

                # 将工具结果加入消息（摘要版本，供 LLM 理解）
                self.append_message("tool", json.dumps({
                    "tool": name,
                    "result_summary": {
                        "status": result.get("status"),
                        "stdout": (result.get("stdout") or "")[:1000],
                        "stderr": (result.get("stderr") or "")[:1000],
                        "has_image": bool(result.get("image_base64")),
                    }
                }, ensure_ascii=False))

                continue

            # --- 普通回复 ---
            if llm_resp["type"] == "response":
                content = llm_resp["content"]
                await self.send_event("log", {"msg": "模型回复", "content": content})
                self.append_message("assistant", content)

                # 若为最终分析 → 结束
                if "最终分析" in content or "完成" in content or "完成任务" in content:
                    await self.send_event("final_report", {"report": content})
                    break

                # Demo：若模型说“完成第1步”
                if "完成第1步" in content or "完成任务1" in content:
                    for t in self.tasks:
                        if t["id"] == 1:
                            t["status"] = "done"

                await self.send_event("task_list", {"tasks": self.tasks})

            await asyncio.sleep(0.1)

        await self.send_event("log", {"msg": "Agent loop 结束", "iterations": it})


# -------------------
# API 端点
# -------------------
class StartRequest(BaseModel):
    user_request: str


@app.post("/start")
async def start_endpoint(user_request: str = Form(...), file: UploadFile = File(...)):
    """
    启动 Agent（同步阻塞方式）。
      - 保存上传的 Excel
      - 创建 Agent 并运行循环
    生产环境可换成任务队列异步运行。
    """
    tmpdir = tempfile.mkdtemp()
    dataset_path = os.path.join(tmpdir, file.filename)
    with open(dataset_path, "wb") as f:
        f.write(await file.read())

    agent = Agent(dataset_path=dataset_path, user_request=user_request, ws_broadcast=manager.broadcast_json)

    await agent.run_loop()

    return JSONResponse({"status": "ok", "message": "Agent finished (check WS for details)"})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "connected", "ts": datetime.utcnow().isoformat() + "Z"})
        while True:
            try:
                msg = await ws.receive_text()
                await ws.send_json({"type": "echo", "payload": msg})
            except Exception:
                await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        manager.disconnect(ws)
