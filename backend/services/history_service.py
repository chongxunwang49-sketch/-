"""
分析历史落库(第一批)

- save_analysis_history:任务完成后把该次分析写入 analysis_history
- compute_score:后端综合评分(与技术分析/情感/风险/RAG 权重一致,供历史列表排序展示)

说明:score 公式与 frontend/components/report_card.py 的 composite_score 保持一致:
  综合评分 = 技术0.35 + 情感0.30 + 风险0.20 + 基本面(RAG)0.15
"""
import json
import logging
from typing import Optional

from sqlalchemy import select

from ..models import History, SessionLocal

logger = logging.getLogger(__name__)


def _tech_score(tech: Optional[dict]) -> float:
    """技术面得分 0-1(基于 RSI/MACD/收盘价与MA20 相对位置)"""
    if not tech:
        return 0.5
    ts = 0.5
    rsi = tech.get("rsi14")
    hist = tech.get("macd_hist")
    close, ma20 = tech.get("close_price"), tech.get("ma20")
    if rsi is not None:
        ts = 0.5 * ts + 0.5 * max(0.0, min(1.0, (rsi - 30) / 40))
    if hist is not None:
        ts = 0.5 * ts + 0.5 * (1.0 if hist > 0 else 0.0)
    if close is not None and ma20:
        ts = 0.5 * ts + 0.5 * (1.0 if close >= ma20 else 0.0)
    return ts


def compute_score(result: dict) -> float:
    """按与前端一致的权重计算综合评分"""
    tech = _tech_score(result.get("technical"))
    sentiment = float((result.get("sentiment") or {}).get("score") or 0.5)
    risk_level = (result.get("risk") or {}).get("risk_level")
    rscore = {"低": 0.8, "中": 0.5, "高": 0.2}.get(risk_level, 0.5)
    has_rag = bool((result.get("report") or {}).get("rag_sources"))
    fundamental = 0.62 if has_rag else 0.5
    return round(0.35 * tech + 0.30 * sentiment + 0.20 * rscore + 0.15 * fundamental, 4)


def save_analysis_history(user_id: Optional[int], result: dict) -> None:
    """把一次分析结果写入 analysis_history。user_id 为空(未登录)时跳过。"""
    if not user_id or not result:
        return
    report = result.get("report") or {}
    try:
        with SessionLocal() as session:
            session.add(History(
                user_id=user_id,
                stock_code=result.get("stock_code", "") or report.get("stock_code", ""),
                company_name=report.get("company_name", ""),
                mode=result.get("mode", "full"),
                score=compute_score(result),
                data_source=result.get("data_source", "real"),
                report_json=json.dumps(result, ensure_ascii=False, default=str),
            ))
            session.commit()
        logger.info("分析历史已入库: user_id=%s code=%s", user_id, report.get("company_name", ""))
    except Exception as e:
        logger.warning("分析历史入库失败(不影响主流程): %s", e)


def list_user_history(user_id: int, limit: int = 50) -> list[dict]:
    """按时间倒序返回用户的历史分析记录(不含 report_json 大字段)"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(History)
            .where(History.user_id == user_id)
            .order_by(History.created_at.desc())
            .limit(limit)
        ).all()
    return [{
        "id": r.id, "stock_code": r.stock_code, "company_name": r.company_name,
        "mode": r.mode, "score": r.score, "data_source": r.data_source,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
    } for r in rows]
