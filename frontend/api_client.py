"""
后端 API 客户端(专业看板升级)

所有对 FastAPI 后端的 HTTP 调用集中在此,统一超时/错误处理。
后端地址可用环境变量 API_BASE 覆盖(Docker 下 frontend 服务指向 http://backend:8000)。
"""
import os

import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")

TIMEOUT = 30          # 普通接口超时
ANALYZE_TIMEOUT = 15  # 启动分析只需等到 task_id 返回,不必等分析完成


class ApiError(Exception):
    """后端不可用或返回错误时的统一异常"""


def _get(path: str, params: dict | None = None, timeout: int = TIMEOUT) -> dict:
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise ApiError(f"GET {path} 失败: {e}") from e


def _post(path: str, json_body: dict | None = None, timeout: int = ANALYZE_TIMEOUT) -> dict:
    try:
        resp = requests.post(f"{API_BASE}{path}", json=json_body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise ApiError(f"POST {path} 失败: {e}") from e


def health() -> dict:
    return _get("/health", timeout=5)


def stock_info(code: str) -> dict:
    """股票基础信息(名称/现价/涨跌幅/技术指标快照)"""
    return _get("/stock/info", {"code": code})


def stock_history(code: str, time_range: str = "3m",
                  start: str = "", end: str = "") -> dict:
    """K线历史(含 MA/MACD/RSI/BOLL 序列)"""
    return _get("/stock/history", {"code": code, "range": time_range, "start": start, "end": end})


def start_analysis(code: str, mode: str = "full") -> dict:
    """异步启动分析,返回 {task_id, status}"""
    return _post("/analyze", {"stock_code": code, "mode": mode})


def task_status(task_id: str) -> dict:
    """轮询任务状态(各 Agent 阶段)"""
    return _get("/task/status", {"task_id": task_id}, timeout=10)


def task_result(task_id: str) -> dict:
    """获取最终报告与中间数据"""
    return _get("/task/result", {"task_id": task_id}, timeout=10)
