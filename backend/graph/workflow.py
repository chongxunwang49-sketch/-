"""
LangGraph 多智能体编排(步骤10+步骤11)

流程图:
  采集(collect)
    ├─▶ 技术分析(technical) ─┐
    └─▶ 情感分析(sentiment) ─┼─▶ 风险评估(risk) ─▶ 报告生成(report) ─▶ END
                              (technical 与 sentiment 并行 fan-out)
  条件路由:collect 后若新闻为空 -> 跳过 sentiment 直接 risk(数据驱动降级)
  异常降级:任一 Agent 抛异常 -> 节点捕获后在 State 打标记 ->
            risk 用规则兜底 / report 生成降级报告,图不崩

编译入口:build_workflow()
执行入口:run_analysis(stock_code)
"""
import logging
import sys
from pathlib import Path
from typing import List, Optional, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 项目根

import pandas as pd  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from ..agents.llm import LLMClient  # noqa: E402
from ..agents.report import run_report_agent  # noqa: E402
from ..agents.risk import run_risk_agent, _rule_based_fallback  # noqa: E402
from ..agents.sentiment import run_sentiment_agent  # noqa: E402
from ..agents.technical import compute_indicators, run_technical_agent  # noqa: E402
from ..models import StockPrice  # noqa: E402
from ..models import engine  # noqa: E402
from ..schemas import AnalysisReport, NewsItem, RiskAssessment, SentimentResult, TechnicalIndicators  # noqa: E402
from sqlalchemy import select  # noqa: E402

logger = logging.getLogger(__name__)

# 复用 scripts 里的采集函数(含三级降级链)
from scripts.fetch_news import fetch_news_data  # noqa: E402
from scripts.fetch_stock_data import fetch_stock_with_degradation  # noqa: E402

# LLM 客户端进程内复用(避免每次节点调用都重新初始化)
_llm_cache: Optional[LLMClient] = None


def _llm() -> LLMClient:
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = LLMClient()
    return _llm_cache


# ------------------------------------------------------------
# State:多智能体之间的共享状态(步骤9/10)
# ------------------------------------------------------------
class WorkflowState(TypedDict):
    stock_code: str
    news_items: List[NewsItem]
    technical: Optional[TechnicalIndicators]
    technical_analysis: Optional[str]
    sentiment: Optional[SentimentResult]
    sentiment_failed: bool
    risk: Optional[RiskAssessment]
    report: Optional[AnalysisReport]
    data_source: str  # real/backup/mock,来自采集降级链


# ------------------------------------------------------------
# 数据层辅助:从数据库读行情/新闻
# ------------------------------------------------------------
def _load_latest_quotes(code: str) -> Optional[pd.DataFrame]:
    """从 PostgreSQL 读最近 60 个交易日行情,用于技术指标计算"""
    with engine.connect() as conn:
        rows = conn.execute(
            select(StockPrice).where(StockPrice.stock_code == code).order_by(StockPrice.date.desc()).limit(60)
        ).all()
    if not rows:
        return None
    df = pd.DataFrame([{
        "date": r.date, "open_price": r.open_price, "close_price": r.close_price,
        "high_price": r.high_price, "low_price": r.low_price, "volume": r.volume,
    } for r in rows])
    return df.sort_values("date").reset_index(drop=True)


def _load_news(code: str) -> List[NewsItem]:
    """从 PostgreSQL 读该股票最近的新闻"""
    from ..models import NewsArticle
    with engine.connect() as conn:
        rows = conn.execute(
            select(NewsArticle).where(NewsArticle.stock_code == code).order_by(NewsArticle.publish_time.desc()).limit(10)
        ).all()
    return [
        NewsItem(stock_code=r.stock_code, title=r.title, content=r.content,
                 publish_time=r.publish_time, source=r.source)
        for r in rows
    ]


# ------------------------------------------------------------
# 节点:5 个 Agent
# ------------------------------------------------------------
def collect_node(state: WorkflowState) -> dict:
    """采集:行情(带三级降级)+ 新闻,写入 State"""
    code = state["stock_code"]
    logger.info("[collect] 开始采集 %s", code)

    # 行情:调三级降级链(主源失败自动降级),数据入库
    result = fetch_stock_with_degradation(code)
    df = _load_latest_quotes(code)
    technical = compute_indicators(df, code) if df is not None else None
    if technical is None:
        logger.warning("[collect] 行情不足 20 条,技术指标不可用")

    # 新闻:刷新并读库(搜索关键词用公司名而非代码)
    try:
        from ..agents.report import COMPANY_NAMES
        keyword = COMPANY_NAMES.get(code, code)
        fetch_news_data(stock_code=code, keyword=keyword)
    except Exception as e:
        logger.warning("[collect] 新闻刷新失败(用库中已有数据): %s", e)
    news = _load_news(code)
    logger.info("[collect] 完成: source=%s, 新闻 %d 条", result.get("source"), len(news))

    return {
        "technical": technical,
        "news_items": news,
        "data_source": result.get("source", "real"),
    }


def technical_node(state: WorkflowState) -> dict:
    """技术分析:指标 -> LLM 解读"""
    tech = state.get("technical")
    if tech is None:
        return {"technical_analysis": "数据不足,无法解读"}
    try:
        analysis = run_technical_agent(tech, _llm())
        return {"technical_analysis": analysis}
    except Exception as e:
        logger.error("[technical] 降级(无技术解读): %s", e)
        return {"technical_analysis": "技术分析暂不可用"}


def sentiment_node(state: WorkflowState) -> dict:
    """情感分析:新闻 -> 情感得分;异常时打降级标记,不中断图"""
    code = state["stock_code"]
    try:
        sentiment = run_sentiment_agent(state.get("news_items") or [], _llm(), code)
        return {"sentiment": sentiment, "sentiment_failed": False}
    except Exception as e:
        logger.error("[sentiment] 降级(返回中性): %s", e)
        return {
            "sentiment": SentimentResult(stock_code=code, score=0.5,
                                         reason="情感分析降级,默认中性", source="degraded"),
            "sentiment_failed": True,
        }


def risk_node(state: WorkflowState) -> dict:
    """风险评估:情感+技术 -> 风险;情感失败时走纯技术规则兜底"""
    code = state["stock_code"]
    if state.get("sentiment_failed"):
        logger.warning("[risk] 情感不可用,改用纯技术指标规则评估")
        risk = _rule_based_fallback(None, state.get("technical_analysis"), code)
    else:
        try:
            risk = run_risk_agent(state.get("sentiment"), state.get("technical_analysis"),
                                  _llm(), code)
        except Exception as e:
            logger.error("[risk] 降级(规则兜底): %s", e)
            risk = _rule_based_fallback(state.get("sentiment"), state.get("technical_analysis"), code)
    return {"risk": risk}


def report_node(state: WorkflowState) -> dict:
    """报告生成:汇总所有环节 -> 最终 Markdown 报告"""
    code = state["stock_code"]
    try:
        report = run_report_agent(
            state.get("sentiment"), state.get("technical_analysis"), state.get("risk"),
            _llm(), code, state.get("data_source", "real"),
        )
        return {"report": report}
    except Exception as e:
        logger.error("[report] 降级(占位报告): %s", e)
        report = AnalysisReport(
            stock_code=code, company_name=code,
            report="## 综合结论\n报告生成环节暂不可用,请稍后重试。",
            data_source=state.get("data_source", "real"),
        )
        return {"report": report}


# ------------------------------------------------------------
# 条件路由:新闻为空时跳过情感分析(步骤10 的 Conditional Edge)
# ------------------------------------------------------------
def _route_after_collect(state: WorkflowState) -> str:
    return "sentiment" if state.get("news_items") else "risk"


# ------------------------------------------------------------
# 构图与执行
# ------------------------------------------------------------
def build_workflow():
    """构建并编译 LangGraph 状态图"""
    g = StateGraph(WorkflowState)

    g.add_node("collect", collect_node)
    g.add_node("technical", technical_node)
    g.add_node("sentiment", sentiment_node)
    g.add_node("risk", risk_node)
    g.add_node("report", report_node)

    g.add_edge(START, "collect")
    # technical 与 sentiment 并行(fan-out 后汇聚到 risk)
    g.add_edge("collect", "technical")
    g.add_conditional_edges("collect", _route_after_collect,
                            {"sentiment": "sentiment", "risk": "risk"})
    g.add_edge("technical", "risk")
    g.add_edge("sentiment", "risk")
    g.add_edge("risk", "report")
    g.add_edge("report", END)

    return g.compile()


def run_analysis(stock_code: str) -> AnalysisReport:
    """
    主执行入口:输入股票代码,跑完整多智能体流程,返回最终报告。
    示例: run_analysis("600519")
    """
    graph = build_workflow()
    result = graph.invoke({
        "stock_code": stock_code,
        "news_items": [],
        "technical": None,
        "technical_analysis": None,
        "sentiment": None,
        "sentiment_failed": False,
        "risk": None,
        "report": None,
        "data_source": "real",
    })
    report = result.get("report")
    if report is None:
        raise RuntimeError("工作流未生成报告")
    logger.info("run_analysis(%s) 完成: 数据源=%s", stock_code, result.get("data_source"))
    return report
