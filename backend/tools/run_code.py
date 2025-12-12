"""
代码执行工具 - 在受控环境中执行 Python 代码
"""
import os
import sys
import json
import base64
import tempfile
import subprocess
import traceback
from pathlib import Path
from typing import Dict, Any, Optional

from config.settings import settings


def tool_run_code(
    code: str,
    dataset_path: str,
    timeout_seconds: Optional[int] = None,
    description: str = ""
) -> Dict[str, Any]:
    """
    在子进程中安全执行 Python 代码
    
    Args:
        code: 要执行的 Python 代码
        dataset_path: 数据集文件路径
        timeout_seconds: 超时时间（秒）
        description: 代码功能描述
    
    Returns:
        执行结果，包含 stdout, stderr, 图片(base64), 结构化结果等
    """
    timeout = timeout_seconds or settings.CODE_TIMEOUT
    
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "script.py"
        result_json_path = Path(tmpdir) / "result.json"
        result_png_path = Path(tmpdir) / "result.png"
        
        # 构建执行脚本
        # 注意：用户代码需要正确缩进
        indented_code = "\n".join("    " + line for line in code.split("\n"))
        
        wrapper_code = f'''
import os
import sys
import json
import traceback

# 设置数据集路径为环境变量，方便代码访问
os.environ["DATASET_PATH"] = r"{dataset_path}"
DATASET_PATH = r"{dataset_path}"

# 设置 matplotlib 后端为 Agg（非交互式）
import matplotlib
matplotlib.use('Agg')

# 导入常用库
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

try:
{indented_code}
except Exception as e:
    print("=== EXECUTION ERROR ===")
    traceback.print_exc()
    print("=== END ERROR ===")

# 确保所有图表都保存
plt.savefig("result.png", dpi=150, bbox_inches='tight') if plt.get_fignums() else None
'''
        
        script_path.write_text(wrapper_code, encoding="utf-8")
        
        try:
            # 在子进程中执行
            env = os.environ.copy()
            env["DATASET_PATH"] = dataset_path
            
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env
            )
            
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            
            # 检查是否有执行错误
            has_error = "=== EXECUTION ERROR ===" in stdout or proc.returncode != 0
            
            # 读取结构化结果
            result_json = None
            if result_json_path.exists():
                try:
                    result_json = json.loads(result_json_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result_json = {"error": "result.json 格式错误"}
            
            # 读取图片
            image_b64 = None
            if result_png_path.exists():
                image_bytes = result_png_path.read_bytes()
                if len(image_bytes) > 100:  # 确保不是空图片
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            
            return {
                "status": "error" if has_error else "success",
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "result_json": result_json,
                "image_base64": image_b64,
                "has_image": image_b64 is not None,
                "description": description
            }
            
        except subprocess.TimeoutExpired as e:
            return {
                "status": "error",
                "error_type": "timeout",
                "message": f"代码执行超时（{timeout}秒）",
                "stdout": e.stdout if e.stdout else "",
                "stderr": e.stderr if e.stderr else ""
            }
        except Exception as e:
            return {
                "status": "error",
                "error_type": "execution_error",
                "message": str(e),
                "traceback": traceback.format_exc()
            }


def validate_code(code: str) -> Dict[str, Any]:
    """
    验证代码安全性（基础检查）
    
    注意：这是 Demo 级别的检查，生产环境需要更严格的沙箱
    """
    dangerous_patterns = [
        "os.system",
        "subprocess.run",
        "subprocess.call",
        "subprocess.Popen",
        "__import__",
        "eval(",
        "exec(",
        "open(",  # 允许特定路径的文件操作
        "shutil.rmtree",
        "os.remove",
        "os.unlink"
    ]
    
    warnings = []
    for pattern in dangerous_patterns:
        if pattern in code:
            # 对于 open 做特殊处理
            if pattern == "open(" and ("result.json" in code or "result.png" in code):
                continue
            warnings.append(f"检测到可能危险的操作: {pattern}")
    
    return {
        "is_safe": len(warnings) == 0,
        "warnings": warnings
    }


def format_code_for_display(code: str) -> str:
    """
    格式化代码用于显示
    """
    lines = code.strip().split("\n")
    # 移除空行并添加行号
    formatted = []
    for i, line in enumerate(lines, 1):
        formatted.append(f"{i:3d} | {line}")
    return "\n".join(formatted)

