"""
后端 API 客户端(专业看板升级 + 用户体系第一批)

所有对 FastAPI 后端的 HTTP 调用集中在此,统一超时/错误处理。
- 认证接口:login/register/me
- 用户接口:update_profile/user_history/watchlist
- 公开接口:health/stock_info/stock_history
- 需登录接口:analyze(带 Authorization: Bearer token)

后端地址可用环境变量 API_BASE 覆盖(Docker 下 frontend 服务指向 http://backend:8000)。
"""
import os

import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")

TIMEOUT = 30          # 普通接口超时
ANALYZE_TIMEOUT = 15  # 启动分析只需等到 task_id 返回,不必等分析完成


class ApiError(Exception):
    """后端不可用或返回错误时的统一异常"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _request(method: str, path: str, *, params: dict | None = None,
             json_body: dict | None = None, token: str | None = None,
             timeout: int = TIMEOUT) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.request(method, f"{API_BASE}{path}",
                                params=params, json=json_body,
                                headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise ApiError(f"{method} {path} 失败: {e}") from e
    if resp.status_code == 401:
        raise ApiError("登录已过期,请重新登录", status_code=401)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ApiError(f"{method} {path} 错误({resp.status_code}): {detail}",
                       status_code=resp.status_code)
    return resp.json()


# ------------------------------------------------------------
# 公开接口
# ------------------------------------------------------------
def health() -> dict:
    return _request("GET", "/health", timeout=5)


def stock_info(code: str) -> dict:
    return _request("GET", "/stock/info", params={"code": code})


def stock_history(code: str, time_range: str = "3m",
                  start: str = "", end: str = "") -> dict:
    return _request("GET", "/stock/history",
                    params={"code": code, "range": time_range, "start": start, "end": end})


def stock_news(code: str, limit: int = 10) -> dict:
    return _request("GET", "/stock/news", params={"code": code, "limit": limit})


def market_indices() -> dict:
    """市场指数行情条(上证/深证/创业板/沪深300/恒生/标普500)"""
    return _request("GET", "/market/indices", timeout=25)


# ------------------------------------------------------------
# 认证接口
# ------------------------------------------------------------
def login(username: str, password: str) -> dict:
    """登录,返回 {token, user}"""
    return _request("POST", "/auth/login", json_body={"username": username, "password": password},
                    timeout=10)


def register(username: str, password: str, email: str = "") -> dict:
    """注册,成功返回 {token, user}"""
    return _request("POST", "/auth/register",
                    json_body={"username": username, "password": password,
                               "email": email or None},
                    timeout=10)


def me(token: str) -> dict:
    """校验并获取当前用户信息"""
    return _request("GET", "/auth/me", token=token, timeout=10)


# ------------------------------------------------------------
# 用户接口(需登录)
# ------------------------------------------------------------
def update_profile(token: str, email: str | None = None,
                   old_password: str | None = None,
                   new_password: str | None = None) -> dict:
    return _request("PUT", "/user/profile",
                    json_body={"email": email, "old_password": old_password,
                               "new_password": new_password},
                    token=token)


def user_history(token: str) -> dict:
    return _request("GET", "/user/history", token=token)


def watchlist_list(token: str) -> dict:
    return _request("GET", "/user/watchlist", token=token)


def watchlist_add(token: str, stock_code: str) -> dict:
    return _request("POST", "/user/watchlist", json_body={"stock_code": stock_code}, token=token)


def watchlist_delete(token: str, stock_code: str) -> dict:
    return _request("DELETE", "/user/watchlist", params={"stock_code": stock_code}, token=token)


# ------------------------------------------------------------
# 分析接口(需登录)
# ------------------------------------------------------------
def start_analysis(code: str, mode: str = "full", token: str | None = None) -> dict:
    """异步启动分析,返回 {task_id, status}"""
    return _request("POST", "/analyze",
                    json_body={"stock_code": code, "mode": mode},
                    token=token, timeout=ANALYZE_TIMEOUT)


def task_status(task_id: str) -> dict:
    return _request("GET", "/task/status", params={"task_id": task_id}, timeout=10)


def task_result(task_id: str) -> dict:
    return _request("GET", "/task/result", params={"task_id": task_id}, timeout=10)


# ------------------------------------------------------------
# RAG 智能问答(第五批)
# ------------------------------------------------------------
def chat(session_id: str, message: str, token: str) -> dict:
    return _request("POST", "/chat", json_body={"session_id": session_id, "message": message},
                    token=token, timeout=60)


def chat_history(session_id: str, token: str) -> dict:
    return _request("GET", "/chat/history", params={"session_id": session_id}, token=token)


def upload_doc(file_bytes: bytes, filename: str, token: str) -> dict:
    try:
        resp = requests.post(
            f"{API_BASE}/chat/upload", files={"file": (filename, file_bytes)},
            headers={"Authorization": f"Bearer {token}"}, timeout=120)
        if resp.status_code == 401:
            raise ApiError("登录已过期,请重新登录", status_code=401)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise ApiError(f"上传失败: {e}") from e


# ------------------------------------------------------------
# 基本面(第二批) / 管理后台(第六批)
# ------------------------------------------------------------
def stock_fundamentals(code: str) -> dict:
    return _request("GET", "/stock/fundamentals", params={"code": code})


def admin_users(token: str) -> dict:
    return _request("GET", "/admin/users", token=token)


def admin_update_user(token: str, user_id: int, role: str | None = None,
                      is_active: bool | None = None) -> dict:
    return _request("PUT", f"/admin/users/{user_id}",
                    json_body={"role": role, "is_active": is_active}, token=token)


def admin_delete_user(token: str, user_id: int) -> dict:
    return _request("DELETE", f"/admin/users/{user_id}", token=token)


def admin_stats(token: str) -> dict:
    return _request("GET", "/admin/stats", token=token)


def admin_data_refresh(token: str) -> dict:
    return _request("POST", "/admin/data/refresh", token=token, timeout=120)
