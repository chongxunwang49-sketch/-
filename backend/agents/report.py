"""
报告生成 Agent(步骤8)
汇总 情感+技术+风险 -> 输出完整 Markdown 报告(AnalysisReport)
"""
import logging
from typing import Optional

from ..schemas import AnalysisReport, RiskAssessment, SentimentResult
from .llm import LLMClient
from .prompts import REPORT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

COMPANY_NAMES = {"600519": "贵州茅台"}


def run_report_agent(sentiment: Optional[SentimentResult],
                     technical_analysis: Optional[str],
                     risk: Optional[RiskAssessment],
                     client: LLMClient,
                     stock_code: str = "600519",
                     data_source: str = "real") -> AnalysisReport:
    """生成最终报告。company_name 默认按代码映射,未知代码用代码本身。"""
    company = COMPANY_NAMES.get(stock_code, stock_code)
    # 注意:用 list + join 拼接,避免"+"与 if/else 表达式优先级混淆导致拼接被截断
    parts = []
    parts.append(f"情感得分：{sentiment.score:.2f}(理由:{sentiment.reason})" if sentiment else "情感得分：无")
    parts.append(f"技术面解读：{technical_analysis or '无'}")
    parts.append(f"风险等级：{risk.risk_level if risk else '未知'}")
    parts.append(f"风险点：{('、'.join(risk.risks)) if risk else '无'}")
    parts.append(f"公司名称：{company}")
    user_prompt = "\n".join(parts)

    if client.provider == "dify":
        # 用户在 dify 搭建的报告生成应用
        out = client.complete_dify({
            "sentiment_score": sentiment.score if sentiment else 0.5,
            "technical_analysis": technical_analysis or "",
            "risk_level": risk.risk_level if risk else "中",
            "company_name": company,
        })
        report = str(out.get("report", ""))
    else:
        report = client.complete(REPORT_SYSTEM_PROMPT, user_prompt)

    result = AnalysisReport(
        stock_code=stock_code,
        company_name=company,
        sentiment=sentiment,
        technical_analysis=technical_analysis,
        risk=risk,
        report=report,
        data_source=data_source,
    )
    logger.info("报告生成完成: %d 字符", len(report))
    return result
