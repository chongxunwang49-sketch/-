"""
FastAPI 后端入口(步骤13 + 专业看板升级)

接口:
  基础数据
    GET  /health               健康检查
    GET  /stock/info           股票基础信息(名称/现价/涨跌幅/技术指标快照)
    GET  /stock/history        K线历史(时间范围 + MA/MACD/RSI/BOLL 指标序列)
  分析任务(异步轮询,前端不再长连接)
    POST /analyze              异步启动分析 -> {task_id}(mode: quick/full)
    GET  /task/status          轮询任务状态(各 Agent 进度/耗时/降级标记)
    GET  /task/result          获取最终报告与全部中间数据
  兼容旧接口(保留,不影响新前端)
    POST /analyze/sync         同步分析(原 /analyze 语义)
    GET  /analyze/stream       SSE 流式分析

启动: uvicorn backend.main:app --reload --port 8000
前端: streamlit run frontend/app.py
"""
import io
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select

from .graph.workflow import _load_latest_quotes, build_workflow
from .models import ChatHistory, StockPrice, User, Watchlist, engine
from .models import SessionLocal
from .services import history_service, stock_meta
from .services import qa as qa_service
from .services.auth import (
    create_token,
    get_current_user,
    get_user_by_name,
    hash_password,
    password_strength,
    verify_password,
)
from .services.task_manager import TaskManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="多智能体股票分析系统", version="2.0")

# 异步任务管理器(后台线程执行分析,前端轮询状态)
task_manager = TaskManager()

# 启动时编译一次工作流,复用实例(SSE 兼容接口用)
_graph = build_workflow()

# ------------------------------------------------------------
# API 调用统计(第六批:监控)
# ------------------------------------------------------------
API_STATS: dict = {"total": 0, "by_path": {}}


@app.middleware("http")
async def _count_api(request: Request, call_next):
    API_STATS["total"] += 1
    path = request.url.path
    API_STATS["by_path"][path] = API_STATS["by_path"].get(path, 0) + 1
    return await call_next(request)


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """管理员权限依赖:非 admin 一律 403"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


class AnalyzeRequest(BaseModel):
    stock_code: str = "600519"
    mode: str = "full"  # quick=跳过情感分析 / full=完整链路

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        return v if v in ("quick", "full") else "full"


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdateRequest(BaseModel):
    email: Optional[str] = None
    old_password: Optional[str] = None
    new_password: Optional[str] = None


class WatchlistAddRequest(BaseModel):
    stock_code: str


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class UserAdminUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _initial_state(code: str, mode: str = "full") -> dict:
    """工作流初始 State(SSE 兼容接口用)"""
    return {
        "stock_code": code,
        "news_items": [],
        "technical": None,
        "technical_analysis": None,
        "sentiment": None,
        "sentiment_failed": False,
        "fundamental": None,
        "valuation": None,
        "flow": None,
        "industry": None,
        "event": None,
        "risk": None,
        "report": None,
        "data_source": "real",
        "mode": mode,
    }


# ------------------------------------------------------------
# 数据层辅助:行情读写
# ------------------------------------------------------------
def _load_history(code: str, start_date: date, end_date: date) -> List:
    """按日期区间从 PostgreSQL 读行情(升序)"""
    with engine.connect() as conn:
        rows = conn.execute(
            select(StockPrice)
            .where(StockPrice.stock_code == code,
                   StockPrice.date >= start_date,
                   StockPrice.date <= end_date)
            .order_by(StockPrice.date)
        ).all()
    return rows


def _f2(v) -> float | None:
    """转两位小数;NaN/None 转 None"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _f3(v) -> float | None:
    """转三位小数;NaN/None 转 None"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _history_payload(code: str, rows: List) -> List[dict]:
    """把行情行转成含 MA/MACD/RSI/BOLL 序列的记录列表(供 Plotly 直接绘图)"""
    df = pd.DataFrame([{
        "date": r.date, "open": r.open_price, "high": r.high_price,
        "low": r.low_price, "close": r.close_price, "volume": r.volume,
    } for r in rows])
    if df.empty:
        return []
    close = df["close"]
    for w in (5, 10, 20, 60):
        df[f"ma{w}"] = close.rolling(w).mean()
    df["boll_mid"] = close.rolling(20).mean()
    df["boll_std"] = close.rolling(20).std()
    df["boll_up"] = df["boll_mid"] + 2 * df["boll_std"]
    df["boll_low"] = df["boll_mid"] - 2 * df["boll_std"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = (ema12 - ema26).ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_dif"] - df["macd_dea"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi14"] = 100 - 100 / (1 + rs)

    out = []
    for r in df.itertuples():
        out.append({
            "date": str(r.date),
            "open": _f2(r.open), "high": _f2(r.high), "low": _f2(r.low), "close": _f2(r.close),
            "volume": int(r.volume),
            "ma5": _f2(r.ma5), "ma10": _f2(r.ma10), "ma20": _f2(r.ma20), "ma60": _f2(r.ma60),
            "boll_up": _f2(r.boll_up), "boll_mid": _f2(r.boll_mid), "boll_low": _f2(r.boll_low),
            "macd_dif": _f3(r.macd_dif), "macd_dea": _f3(r.macd_dea), "macd_hist": _f3(r.macd_hist),
            "rsi14": _f2(r.rsi14),
        })
    return out


def _latest_indicators(code: str) -> dict | None:
    """基于最近 60 个交易日计算技术指标快照(行情不足 20 条返回 None)"""
    df = _load_latest_quotes(code)
    if df is None or len(df) < 20:
        return None
    from .agents.technical import compute_indicators
    ti = compute_indicators(df, code)
    if ti is None:
        return None
    close = df["close_price"]
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    return {
        "close_price": ti.close_price,
        "pct_change": ti.pct_change,
        "rsi14": ti.rsi14,
        "macd_dif": ti.macd_dif,
        "macd_dea": ti.macd_dea,
        "macd_hist": ti.macd_hist,
        "ma5": ti.ma5, "ma10": ti.ma10, "ma20": ti.ma20,
        "boll_up": _f2(ma20 + 2 * std20),
        "boll_mid": _f2(ma20),
        "boll_low": _f2(ma20 - 2 * std20),
    }


def _quotes_to_list(code: str) -> List[dict]:
    """从数据库读行情,转成前端 K线可用的记录列表(SSE 兼容接口用)"""
    df = _load_latest_quotes(code)
    if df is None:
        return []
    return [{
        "date": str(r["date"]),
        "open": float(r["open_price"]),
        "high": float(r["high_price"]),
        "low": float(r["low_price"]),
        "close": float(r["close_price"]),
        "volume": int(r["volume"]),
    } for r in df.to_dict("records")]


# ------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-agent-system"}


# ------------------------------------------------------------
# 启动:建表 + 管理员种子
# ------------------------------------------------------------
def _seed_admin() -> None:
    """首次启动时创建管理员账号(env 可配,默认 admin/admin123)"""
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    if get_user_by_name(admin_user) is None:
        with SessionLocal() as session:
            session.add(User(username=admin_user, password_hash=hash_password(admin_pass),
                             email=None, role="admin"))
            session.commit()
        logger.info("已创建管理员账号: %s", admin_user)


@app.on_event("startup")
def _startup():
    try:
        from .models import create_tables
        create_tables()          # 幂等建表(补齐 users/watchlist/analysis_history/chat_history)
        _seed_admin()
    except Exception as e:
        logger.warning("启动建表/种子初始化失败(不影响进程启动): %s", e)
    try:
        from .services.scheduler import start_scheduler
        start_scheduler()        # 第二批:定时数据采集(每日+每6小时)
    except Exception as e:
        logger.warning("数据调度器启动失败(不影响服务): %s", e)


# ------------------------------------------------------------
# 认证:注册 / 登录 / 当前用户
# ------------------------------------------------------------
@app.post("/auth/register")
def register(req: RegisterRequest):
    """用户注册:用户名唯一 + 密码强度检测,成功直接返回 token(免二次登录)"""
    username = req.username.strip()
    if not (3 <= len(username) <= 20) or not username.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="用户名需为 3-20 位字母/数字/下划线")
    if get_user_by_name(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    strength = password_strength(req.password)
    if not strength["ok"]:
        raise HTTPException(status_code=400,
                            detail=f"密码强度不足({strength['label']}),建议至少 8 位且含大小写字母/数字")
    user = User(username=username, password_hash=hash_password(req.password),
                email=(req.email or "").strip() or None, role="user")
    with SessionLocal() as session:
        session.add(user)
        session.commit()
        session.refresh(user)
    token = create_token(user)
    return {"token": token, "user": _user_payload(user)}


@app.post("/auth/login")
def login(req: LoginRequest):
    """用户登录,校验密码并更新 last_login,返回 token"""
    user = get_user_by_name(req.username.strip())
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user.last_login = datetime.now()
    with SessionLocal() as session:
        session.add(user)
        session.commit()
    token = create_token(user)
    return {"token": token, "user": _user_payload(user)}


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    """返回当前登录用户信息(用于前端会话校验)"""
    return _user_payload(user)


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else None,
        "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
    }


# ------------------------------------------------------------
# 用户中心:资料 / 历史 / 自选股
# ------------------------------------------------------------
@app.put("/user/profile")
def update_profile(req: ProfileUpdateRequest, user: User = Depends(get_current_user)):
    """更新资料:邮箱或修改密码(改密码需验证当前密码)"""
    if req.email is not None:
        user.email = req.email.strip() or None
    if req.new_password:
        if not req.old_password or not verify_password(req.old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="当前密码不正确")
        strength = password_strength(req.new_password)
        if not strength["ok"]:
            raise HTTPException(status_code=400, detail="新密码强度不足")
        user.password_hash = hash_password(req.new_password)
    with SessionLocal() as session:
        session.add(user)
        session.commit()
    return {"ok": True, "user": _user_payload(user)}


@app.get("/user/history")
def user_history(user: User = Depends(get_current_user)):
    """当前用户的历史分析记录(时间倒序)"""
    return {"items": history_service.list_user_history(user.id)}


def _watchlist_quote(stock_code: str) -> dict:
    """读取自选股最新价/涨跌幅(库中有数据时),无数据返回 None"""
    try:
        rows = _load_history(stock_code, date(1900, 1, 1), date.today())
    except Exception:
        rows = []
    if len(rows) < 2:
        return {"price": None, "pct_change": None}
    latest, prev = rows[-1], rows[-2]
    pct = round((latest.close_price / prev.close_price - 1) * 100, 2)
    return {"price": latest.close_price, "pct_change": pct}


@app.get("/user/watchlist")
def watchlist_list(user: User = Depends(get_current_user)):
    """当前用户自选股列表(附最新价/涨跌幅)"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Watchlist)
            .where(Watchlist.user_id == user.id)
            .order_by(Watchlist.sort_order, Watchlist.id)
        ).all()
    items = []
    for r in rows:
        quote = _watchlist_quote(r.stock_code)
        items.append({
            "stock_code": r.stock_code,
            "stock_name": r.stock_name or stock_meta.lookup_name(r.stock_code),
            "price": quote["price"],
            "pct_change": quote["pct_change"],
            "sort_order": r.sort_order,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
        })
    return {"items": items}


@app.post("/user/watchlist")
def watchlist_add(req: WatchlistAddRequest, user: User = Depends(get_current_user)):
    """添加自选股(重复则 409)"""
    code = req.stock_code.strip()
    with SessionLocal() as session:
        exists = session.scalar(select(Watchlist).where(
            Watchlist.user_id == user.id, Watchlist.stock_code == code))
        if exists:
            raise HTTPException(status_code=409, detail="该股票已在自选股中")
        session.add(Watchlist(user_id=user.id, stock_code=code,
                              stock_name=stock_meta.lookup_name(code)))
        session.commit()
    return {"ok": True, "stock_code": code, "stock_name": stock_meta.lookup_name(code)}


@app.delete("/user/watchlist")
def watchlist_delete(stock_code: str, user: User = Depends(get_current_user)):
    """从自选股删除"""
    with SessionLocal() as session:
        session.execute(delete(Watchlist).where(
            Watchlist.user_id == user.id, Watchlist.stock_code == stock_code))
        session.commit()
    return {"ok": True}


# ------------------------------------------------------------
# 第二批:基本面数据
# ------------------------------------------------------------
@app.get("/stock/fundamentals")
def stock_fundamentals(code: str = "600519"):
    """基本面 + 估值数据(最佳努力 AKShare,失败返回 None 与数据源标记)"""
    fund, val = None, None
    source = "none"
    try:
        import akshare as ak
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2023")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                fund = {"revenue_growth": _f2(last.get("主营业务收入增长率")),
                        "roe": _f2(last.get("净资产收益率")),
                        "profit_margin": _f2(last.get("销售净利率"))}
        except Exception as e:
            logger.debug("fundamentals 财务数据失败: %s", e)
        try:
            df2 = ak.stock_a_indicator_lg(symbol=code)
            if df2 is not None and not df2.empty:
                last = df2.iloc[-1]
                pe = _f2(last.get("pe_ttm"))
                pe_series = df2["pe_ttm"].dropna()
                val = {"pe": pe, "pb": _f2(last.get("pb")),
                       "pe_percentile": round(float((pe_series <= pe).mean()), 3)
                       if pe is not None and len(pe_series) else None}
        except Exception as e:
            logger.debug("fundamentals 估值数据失败: %s", e)
        if fund or val:
            source = "real"
    except Exception as e:
        logger.warning("/stock/fundamentals 失败: %s", e)
    return {"code": code, "fundamental": fund, "valuation": val, "data_source": source}


# ------------------------------------------------------------
# 第五批:RAG 智能问答"股小智"
# ------------------------------------------------------------
@app.post("/chat")
def chat(req: ChatRequest, user: User = Depends(get_current_user)):
    """RAG 问答:检索知识库 + 多轮上下文 + LLM 回答(引用来源)"""
    session_id = req.session_id or qa_service.new_session_id()
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    return qa_service.answer_question(user.id, session_id, req.message.strip())


@app.get("/chat/history")
def chat_history(session_id: str, user: User = Depends(get_current_user)):
    """某会话的完整对话记录"""
    return {"items": qa_service.list_history(user.id, session_id)}


@app.get("/chat/sessions")
def chat_sessions(user: User = Depends(get_current_user)):
    """当前用户的历史会话目录(按最近对话倒序),供股小智侧栏展示"""
    from sqlalchemy import func, select
    with SessionLocal() as session:
        rows = session.execute(
            select(ChatHistory.session_id, func.count(ChatHistory.id),
                   func.max(ChatHistory.created_at))
            .where(ChatHistory.user_id == user.id)
            .group_by(ChatHistory.session_id)
            .order_by(func.max(ChatHistory.created_at).desc())
        ).all()
    return {"items": [
        {"session_id": sid, "count": c,
         "last_at": str(ts)[:16] if ts else None}
        for sid, c, ts in rows
    ]}


@app.post("/chat/upload")
async def chat_upload(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """上传 PDF/TXT 扩充知识库(第五批);入库带超时熔断,避免 embedding 服务不可用时挂死"""
    data = await file.read()
    filename = file.filename or "doc"
    try:
        if filename.lower().endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        else:
            text = data.decode("utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(qa_service.ingest_document, text, filename)
    try:
        chunks = future.result(timeout=90)
    except concurrent.futures.TimeoutError:
        logger.warning("知识库入库超时(embedding 服务不可用?)")
        raise HTTPException(status_code=504, detail="文档入库超时:向量化服务不可用")
    except Exception as e:
        logger.warning("知识库上传失败: %s", e)
        raise HTTPException(status_code=500, detail=f"文档入库失败: {e}")
    finally:
        executor.shutdown(wait=False)
    return {"ok": True, "chunks": chunks, "source": filename}


# ------------------------------------------------------------
# 第六批:管理后台(仅管理员)
# ------------------------------------------------------------
@app.get("/admin/users")
def admin_users(_: User = Depends(get_admin_user)):
    """用户列表(含禁用状态)"""
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.created_at.desc())).all()
    return {"items": [{
        "id": u.id, "username": u.username, "email": u.email, "role": u.role,
        "is_active": bool(u.is_active),
        "created_at": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else None,
        "last_login": u.last_login.strftime("%Y-%m-%d %H:%M:%S") if u.last_login else None,
    } for u in rows]}


@app.put("/admin/users/{user_id}")
def admin_update_user(user_id: int, req: UserAdminUpdate, admin: User = Depends(get_admin_user)):
    """修改用户角色 / 启用禁用"""
    with SessionLocal() as session:
        u = session.get(User, user_id)
        if u is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user_id == admin.id:
            raise HTTPException(status_code=400, detail="不能修改自己")
        if req.role is not None:
            u.role = req.role if req.role in ("admin", "user") else u.role
        if req.is_active is not None:
            u.is_active = req.is_active
        session.add(u)
        session.commit()
    return {"ok": True, "id": user_id, "role": u.role, "is_active": bool(u.is_active)}


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: User = Depends(get_admin_user)):
    """删除用户(连带自选股/历史/对话)"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    from .models import ChatHistory, History
    with SessionLocal() as session:
        session.execute(delete(Watchlist).where(Watchlist.user_id == user_id))
        session.execute(delete(History).where(History.user_id == user_id))
        session.execute(delete(ChatHistory).where(ChatHistory.user_id == user_id))
        u = session.get(User, user_id)
        if u is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        session.delete(u)
        session.commit()
    return {"ok": True, "id": user_id}


@app.get("/admin/stats")
def admin_stats(_: User = Depends(get_admin_user)):
    """系统监控:用户数/分析任务/API 调用/LLM token 消耗/CPU内存(psutil,缺失时 None)"""
    from .agents import llm as llm_mod
    with SessionLocal() as session:
        users = session.scalar(select(func.count(User.id))) or 0
        from .models import History
        tasks = session.scalar(select(func.count(History.id))) or 0
    # 系统资源(psutil 缺失时返回 None,前端自动降级为业务指标百分比,不阻塞接口)
    sys_stats = None
    try:
        import psutil
        mem = psutil.virtual_memory()
        sys_stats = {
            "cpu_percent": round(psutil.cpu_percent(interval=0.3), 1),
            "memory_percent": round(mem.percent, 1),
            "memory_used_gb": round(mem.used / 1024 ** 3, 1),
            "memory_total_gb": round(mem.total / 1024 ** 3, 1),
            "disk_percent": round(psutil.disk_usage("/").percent, 1),
        }
    except Exception:
        sys_stats = None
    return {
        "users": users, "analysis_tasks": tasks,
        "api_calls": API_STATS.get("total", 0),
        "api_by_path": dict(sorted(API_STATS.get("by_path", {}).items(), key=lambda kv: -kv[1])[:10]),
        "llm_stats": llm_mod.get_llm_stats(),
        "scheduler": "running",
        "sys_stats": sys_stats,
    }


@app.post("/admin/data/refresh")
def admin_data_refresh(_: User = Depends(get_admin_user)):
    """手动触发数据采集(后台线程执行,前端轮询 /admin/collect/status 看进度)"""
    import threading
    from .services.scheduler import COLLECT_PROGRESS, _collect_watchlist_stocks
    _INDEX_CACHE.update({"ts": 0.0, "data": None})  # 清除指数缓存
    if COLLECT_PROGRESS.get("running"):
        return {"ok": False, "message": "采集正在进行中", "stocks_refreshed": 0}
    threading.Thread(target=_collect_watchlist_stocks, daemon=True).start()
    return {"ok": True, "message": "采集已启动", "stocks_refreshed": 0}


@app.get("/admin/collect/status")
def admin_collect_status(_: User = Depends(get_admin_user)):
    """爬虫进度(管理后台轮询):{running,total,current,stock,message,updated_at}"""
    from .services.scheduler import COLLECT_PROGRESS
    return dict(COLLECT_PROGRESS)


@app.get("/admin/data")
def admin_data(limit: int = 50, _: User = Depends(get_admin_user)):
    """爬虫数据集列表:最近行情 + 新闻(管理后台专用列表窗口)"""
    from .models import NewsArticle, StockPrice
    with SessionLocal() as session:
        prices = (session.query(StockPrice)
                  .order_by(StockPrice.date.desc(), StockPrice.stock_code)
                  .limit(limit).all())
        news = (session.query(NewsArticle)
                .order_by(NewsArticle.publish_time.desc())
                .limit(limit).all())
        total_prices = session.query(StockPrice).count()
        total_news = session.query(NewsArticle).count()
    return {
        "total_prices": total_prices,
        "total_news": total_news,
        "prices": [{
            "id": p.id, "stock_code": p.stock_code, "date": str(p.date),
            "open": p.open_price, "high": p.high_price,
            "low": p.low_price, "close": p.close_price, "volume": p.volume,
        } for p in prices],
        "news": [{
            "id": n.id, "stock_code": n.stock_code, "title": n.title,
            "source": n.source,
            "publish_time": str(n.publish_time)[:19] if n.publish_time else None,
        } for n in news],
    }


# ------------------------------------------------------------
# 基础数据:股票信息 / 历史行情
# ------------------------------------------------------------
@app.get("/stock/info")
def stock_info(code: str = "600519"):
    """返回基础信息(名称/现价/涨跌幅/最新技术指标快照)。不触发网络采集,仅读库。"""
    name = stock_meta.lookup_name(code)
    try:
        rows = _load_history(code, date(1900, 1, 1), date.today())
    except Exception as e:
        logger.warning("/stock/info 读库失败: %s", e)
        rows = []
    if len(rows) < 2:
        return {"code": code, "name": name, "price": None, "pct_change": None,
                "latest_date": None, "open": None, "high": None, "low": None,
                "volume": None, "data_source": "no_data", "indicators": None}
    latest, prev = rows[-1], rows[-2]
    pct = round((latest.close_price / prev.close_price - 1) * 100, 2)
    return {
        "code": code, "name": name,
        "price": latest.close_price, "pct_change": pct,
        "latest_date": str(latest.date),
        "open": latest.open_price, "high": latest.high_price,
        "low": latest.low_price, "volume": latest.volume,
        "data_source": "db", "indicators": _latest_indicators(code),
    }


# 市场指数行情条缓存(5 分钟内复用,避免每次看板刷新都触发 AKShare)
_INDEX_CACHE: dict = {"ts": 0.0, "data": None}


@app.get("/market/indices")
def market_indices():
    """市场指数行情条:上证/深证/创业板/沪深300/恒生/标普500。
    优先实时抓取(A股指数),失败返回缓存或 None 占位,source 标记数据新鲜度。"""
    now = time.time()
    if _INDEX_CACHE["data"] and now - _INDEX_CACHE["ts"] < 300:
        return _INDEX_CACHE["data"]

    base = [
        {"code": "sh000001", "name": "上证指数"},
        {"code": "sz399001", "name": "深证成指"},
        {"code": "sz399006", "name": "创业板指"},
        {"code": "sh000300", "name": "沪深300"},
        {"code": "hkHSI", "name": "恒生指数"},
        {"code": "usSPX", "name": "标普500"},
    ]
    prices = {i["name"]: {"price": None, "pct": None} for i in base}
    source = "no_data"
    # 新浪日线兜底符号表:A股三大指数
    sina_symbols = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    try:
        import akshare as ak
        spot = ak.stock_zh_index_spot_em()          # A股指数实时(东财)
        for _, row in spot.iterrows():
            name = str(row.get("名称", ""))
            if name in prices:
                prices[name] = {"price": _f2(row.get("最新价")), "pct": _f2(row.get("涨跌幅"))}
        source = "real"
    except Exception as e:
        logger.warning("/market/indices 东财实时抓取失败,改用新浪日线兜底: %s", e)
        source = "no_data"
        try:
            import akshare as ak
            for name, symbol in sina_symbols.items():
                df = ak.stock_zh_index_daily(symbol=symbol)   # 新浪通道(与行情采集备用源同源)
                if df is not None and len(df) >= 2:
                    last, prev = df["close"].iloc[-1], df["close"].iloc[-2]
                    prices[name] = {"price": _f2(last),
                                    "pct": _f2((last / prev - 1) * 100)}
            if any(v["price"] is not None for v in prices.values()):
                source = "backup"
        except Exception as e2:
            logger.warning("/market/indices 新浪日线兜底也失败: %s", e2)

    # 恒生/标普:尝试,失败保留 None
    try:
        import akshare as ak
        hk = ak.stock_hk_index_spot_sina()           # 恒生指数
        for _, row in hk.iterrows():
            nm = str(row.get("名称", ""))
            if "恒生" in nm and "恒生" in prices:
                prices["恒生指数"] = {"price": _f2(row.get("最新价")), "pct": _f2(row.get("涨跌幅"))}
    except Exception as e:
        logger.debug("/market/indices 恒生抓取失败(忽略): %s", e)

    data = {"items": [{**i, "price": prices[i["name"]]["price"],
                       "pct": prices[i["name"]]["pct"]} for i in base],
            "source": source, "updated_at": datetime.now().strftime("%H:%M:%S")}
    _INDEX_CACHE.update({"ts": now, "data": data})
    return data


@app.get("/stock/news")
def stock_news(code: str = "600519", limit: int = 10):
    """个股新闻列表(来自 NewsArticle 表,供舆情 Tab/看板)"""
    from .models import NewsArticle
    with engine.connect() as conn:
        rows = conn.execute(
            select(NewsArticle)
            .where(NewsArticle.stock_code == code)
            .order_by(NewsArticle.publish_time.desc())
            .limit(limit)
        ).all()
    return {"items": [{
        "title": r.title,
        "content": (r.content or "")[:200],
        "publish_time": str(r.publish_time)[:19] if r.publish_time else None,
        "source": r.source or "",
    } for r in rows]}


@app.get("/stock/history")
def stock_history(
    code: str = "600519",
    range: str = Query("3m", alias="range", description="1m/3m/6m/1y/custom"),
    start: str = Query("", alias="start", description="自定义起始日期 YYYY-MM-DD"),
    end: str = Query("", alias="end", description="自定义结束日期 YYYY-MM-DD"),
):
    """K线历史:按时间范围读库并返回 MA/MACD/RSI/BOLL 序列。库中无数据时按需采集(最佳努力)。"""
    days = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    ndays = days.get(range, 90)
    end_date = date.today()
    if end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            pass
    if start:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            start_date = end_date - timedelta(days=ndays)
    else:
        start_date = end_date - timedelta(days=ndays)

    rows = _load_history(code, start_date, end_date)
    if not rows:
        # 首次访问该股票:触发三级降级采集,让图表有数据可画
        try:
            from scripts.fetch_stock_data import fetch_stock_with_degradation
            fetch_stock_with_degradation(code, max(ndays, 90))
        except Exception as e:
            logger.warning("/stock/history 按需采集失败: %s", e)
        rows = _load_history(code, start_date, end_date)

    payload = _history_payload(code, rows) if rows else []
    return {"code": code, "name": stock_meta.lookup_name(code), "rows": payload, "count": len(payload)}


# ------------------------------------------------------------
# 异步分析任务
# ------------------------------------------------------------
@app.post("/analyze")
def start_analysis(req: AnalyzeRequest, user: User = Depends(get_current_user)):
    """异步启动分析,立即返回 task_id。mode: quick=跳过情感分析(更快) / full=完整链路
    需要登录;分析完成后自动写入该用户的 analysis_history。"""
    task = task_manager.create(req.stock_code, mode=req.mode, user_id=user.id)
    logger.info("启动分析任务: task_id=%s code=%s mode=%s user=%s",
                task.task_id, req.stock_code, req.mode, user.username)
    return {"task_id": task.task_id, "status": task.status, "stock_code": req.stock_code}


@app.get("/task/status")
def task_status(task_id: str):
    """轮询任务状态:各 Agent 阶段(等待/运行/完成/跳过/失败)+ 耗时 + 降级标记"""
    task = task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return task.to_dict()


@app.get("/task/result")
def task_result(task_id: str):
    """获取最终报告与全部中间数据(任务未完成时返回 status=running)"""
    task = task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if task.status == "running":
        return {"task_id": task_id, "status": "running", "result": None}
    if task.status == "failed":
        return {"task_id": task_id, "status": "failed", "error": task.error, "result": None}
    return {"task_id": task_id, "status": "completed", "result": task.result}


# ------------------------------------------------------------
# 兼容旧接口(保留)
# ------------------------------------------------------------
@app.post("/analyze/sync")
def analyze_sync(req: AnalyzeRequest):
    """同步分析:跑完整工作流,返回报告与 K 线数据(旧 /analyze 语义)"""
    from .graph.workflow import run_analysis
    report = run_analysis(req.stock_code, mode=req.mode)
    return {
        "report": report.model_dump(mode="json"),
        "quotes": _quotes_to_list(req.stock_code),
    }


@app.get("/analyze/stream")
def analyze_stream(stock_code: str = "600519"):
    """SSE 流式分析:每跑完一个 Agent 推一个事件,前端据此渲染进度条(旧接口,保留)"""

    def gen():
        try:
            events = _graph.stream(_initial_state(stock_code))
            report_data = None
            for event in events:
                node = next(iter(event))
                update = event[node]
                if node == "report" and update.get("report"):
                    report_data = update["report"].model_dump(mode="json")
                yield f"data: {json.dumps({'node': node}, ensure_ascii=False)}\n\n"
            quotes = _quotes_to_list(stock_code)
            yield f"data: {json.dumps({'node': 'done', 'report': report_data, 'quotes': quotes}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("流式分析失败")
            yield f"data: {json.dumps({'node': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
