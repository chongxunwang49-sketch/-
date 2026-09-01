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
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select

from .graph.workflow import _load_latest_quotes, build_workflow
from .models import StockPrice, User, Watchlist, engine
from .models import SessionLocal
from .services import history_service, stock_meta
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


def _initial_state(code: str, mode: str = "full") -> dict:
    """工作流初始 State(SSE 兼容接口用)"""
    return {
        "stock_code": code,
        "news_items": [],
        "technical": None,
        "technical_analysis": None,
        "sentiment": None,
        "sentiment_failed": False,
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
