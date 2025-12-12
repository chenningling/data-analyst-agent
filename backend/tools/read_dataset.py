"""
数据集读取工具
"""
import pandas as pd
from typing import Dict, Any, Optional, List
from pathlib import Path


def tool_read_dataset(
    dataset_path: str,
    preview_rows: int = 5,
    sheet_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    读取数据集并返回预览信息
    
    Args:
        dataset_path: 数据文件路径
        preview_rows: 预览行数
        sheet_name: Excel Sheet 名称（仅对 Excel 文件有效）
    
    Returns:
        包含数据预览、schema、统计信息的字典
    """
    try:
        path = Path(dataset_path)
        
        if not path.exists():
            return {"status": "error", "message": f"文件不存在: {dataset_path}"}
        
        # 根据文件类型读取
        suffix = path.suffix.lower()
        
        if suffix in [".xlsx", ".xls"]:
            # 读取 Excel 文件
            excel_file = pd.ExcelFile(dataset_path)
            sheet_names = excel_file.sheet_names
            
            if sheet_name:
                df = pd.read_excel(dataset_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(dataset_path, sheet_name=0)
                sheet_name = sheet_names[0]
                
        elif suffix == ".csv":
            df = pd.read_csv(dataset_path)
            sheet_names = ["default"]
            sheet_name = "default"
        else:
            return {"status": "error", "message": f"不支持的文件格式: {suffix}"}
        
        # 获取数据预览
        preview = df.head(preview_rows).to_dict(orient="records")
        
        # 获取列信息
        schema = []
        for col in df.columns:
            col_info = {
                "column": col,
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
                "null_count": int(df[col].isnull().sum()),
                "unique_count": int(df[col].nunique())
            }
            
            # 数值列添加统计信息
            if pd.api.types.is_numeric_dtype(df[col]):
                col_info["min"] = float(df[col].min()) if not pd.isna(df[col].min()) else None
                col_info["max"] = float(df[col].max()) if not pd.isna(df[col].max()) else None
                col_info["mean"] = float(df[col].mean()) if not pd.isna(df[col].mean()) else None
            
            # 字符串列添加样例值
            if df[col].dtype == "object":
                sample_values = df[col].dropna().head(3).tolist()
                col_info["sample_values"] = sample_values
                
            schema.append(col_info)
        
        # 基本统计
        stats = {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "memory_usage_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
            "missing_cells": int(df.isnull().sum().sum()),
            "missing_percentage": round(df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100, 2)
        }
        
        result = {
            "status": "success",
            "file_info": {
                "path": dataset_path,
                "format": suffix,
                "sheet_names": sheet_names if suffix in [".xlsx", ".xls"] else None,
                "current_sheet": sheet_name
            },
            "preview": preview,
            "schema": schema,
            "statistics": stats
        }
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }


def get_all_sheets_preview(dataset_path: str, preview_rows: int = 3) -> Dict[str, Any]:
    """
    获取 Excel 文件所有 Sheet 的预览
    """
    try:
        path = Path(dataset_path)
        if path.suffix.lower() not in [".xlsx", ".xls"]:
            return {"status": "error", "message": "仅支持 Excel 文件"}
        
        excel_file = pd.ExcelFile(dataset_path)
        sheets_info = {}
        
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(dataset_path, sheet_name=sheet_name)
            sheets_info[sheet_name] = {
                "rows": len(df),
                "columns": list(df.columns),
                "preview": df.head(preview_rows).to_dict(orient="records")
            }
        
        return {
            "status": "success",
            "sheets": sheets_info,
            "total_sheets": len(excel_file.sheet_names)
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

