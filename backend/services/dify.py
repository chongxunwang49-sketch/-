"""
dify 工作流调用服务

dify 侧搭了 4 个角色应用(情感/技术/风险/报告),各自有独立的 app_id + api_key。
本模块封装调用:LLM_PROVIDER=dify 时,各 Agent 通过 call_workflow(role, inputs) 调用对应应用。

.env 配置(4 组,见 .env.example):
  DIFY_BASE_URL=http://localhost/v1
  DIFY_SENTIMENT_APP_ID / DIFY_SENTIMENT_API_KEY
  DIFY_TECHNICAL_APP_ID / DIFY_TECHNICAL_API_KEY
  DIFY_RISK_APP_ID       / DIFY_RISK_API_KEY
  DIFY_REPORT_APP_ID     / DIFY_REPORT_API_KEY
"""
import logging
import os

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DIFY_BASE = os.getenv("DIFY_BASE_URL", "http://localhost/v1").rstrip("/")


def _cfg(role: str) -> dict:
    """返回某个角色的 {app_id, api_key}"""
    return {
        "app_id": os.getenv(f"DIFY_{role.upper()}_APP_ID", ""),
        "api_key": os.getenv(f"DIFY_{role.upper()}_API_KEY", ""),
    }


def call_workflow(role: str, inputs: dict, timeout: int = 180) -> dict:
    """
    调用 dify 工作流(blocking),返回 outputs 字典。
    :param role: sentiment / technical / risk / report
    """
    cfg = _cfg(role)
    if not cfg["app_id"] or not cfg["api_key"]:
        raise RuntimeError(f"dify 角色 {role} 未配置 DIFY_{role.upper()}_APP_ID/API_KEY")

    url = f"{DIFY_BASE}/workflows/run"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "X-App-Id": cfg["app_id"],
        "Content-Type": "application/json",
    }
    payload = {"inputs": inputs, "response_mode": "blocking", "user": "stock-agent"}
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"dify[{role}] 请求失败: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"dify[{role}] 返回 {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("data", {}).get("outputs", {})
