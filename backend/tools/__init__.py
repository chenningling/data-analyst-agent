"""
工具模块 - 提供 Agent 可调用的工具
"""
from tools.read_dataset import tool_read_dataset
from tools.run_code import tool_run_code

__all__ = ["tool_read_dataset", "tool_run_code"]

# 工具 Schema 定义（供 LLM Function Calling 使用）
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_dataset",
            "description": "读取上传的数据集，返回数据预览、列信息和基本统计信息。支持 Excel 和 CSV 格式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "preview_rows": {
                        "type": "integer",
                        "description": "预览的行数，默认为 5",
                        "default": 5
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Excel 文件的 Sheet 名称，默认读取第一个 Sheet",
                        "default": None
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": """在受控环境中执行 Python 代码进行数据分析。
代码可以：
- 使用 pandas、numpy、matplotlib、seaborn 等库
- 读取数据文件（路径通过 DATASET_PATH 环境变量获取）
- 保存图表到 'result.png'
- 保存结构化结果到 'result.json'
- 打印分析结果到 stdout""",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的 Python 代码"
                    },
                    "description": {
                        "type": "string",
                        "description": "代码功能的简要描述"
                    }
                },
                "required": ["code"]
            }
        }
    }
]

