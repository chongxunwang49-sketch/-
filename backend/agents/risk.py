"""
风险评估 Agent(步骤8)
输入:情感得分 + 技术解读 -> 输出:风险等级/风险点/总结(RiskAssessment)
"""
import logging
from typing import Optional

from ..schemas import RiskAssessment, SentimentResult
from .llm import LLMClient, LLMError, extract_json
from .prompts import RISK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def run_risk_agent(sentiment: Optional[SentimentResult], technical_analysis: Optional[str],
                   client: LLMClient, stock_code: str = "600519") -> RiskAssessment:
    """综合情感与技术,评估风险。任一路径失败时用规则兜底(不抛异常)。"""
    score_txt = f"{sentiment.score:.2f}" if sentiment else "未知"
    tech_txt = technical_analysis or "无技术面数据"
    user_prompt = f"情感得分：{score_txt}\n技术面解读：{tech_txt}"

    try:
        if client.provider == "dify":
            # 用户在 dify 搭建的风险评估应用,输入变量 sentiment_score / technical_analysis
            out = client.complete_dify({
                "sentiment_score": float(score_txt) if sentiment else 0.5,
                "technical_analysis": tech_txt,
            })
            return RiskAssessment(
                stock_code=stock_code,
                risk_level=str(out.get("risk_level", "中")),
                risks=[str(r) for r in out.get("risks", [])],
                summary=str(out.get("summary", "")),
            )
        text = client.complete(RISK_SYSTEM_PROMPT, user_prompt)
        data = extract_json(text)
        return RiskAssessment(
            stock_code=stock_code,
            risk_level=str(data.get("risk_level", "中")),
            risks=[str(r) for r in data.get("risks", [])],
            summary=str(data.get("summary", "")),
        )
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("风险评估 LLM 失败,回退规则兜底: %s", e)
        return _rule_based_fallback(sentiment, technical_analysis, stock_code)


def _rule_based_fallback(sentiment: Optional[SentimentResult], technical_analysis: Optional[str],
                         stock_code: str) -> RiskAssessment:
    """规则兜底:模型不可用时用确定性规则给出保守评估,保证流程不断链。"""
    level = "中"
    if sentiment is not None:
        if sentiment.score < 0.3:
            level = "高"
        elif sentiment.score > 0.7:
            level = "低"
    risks = ["LLM 风险评估不可用,采用规则兜底", "请结合更多信息谨慎判断"]
    if technical_analysis and "空头" in technical_analysis:
        level = "高"
        risks.insert(0, "技术面偏空")
    return RiskAssessment(stock_code=stock_code, risk_level=level,
                          risks=risks, summary="规则兜底评估")
