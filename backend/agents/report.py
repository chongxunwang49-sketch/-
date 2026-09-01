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
                     data_source: str = "real",
                     rag_sources: Optional[list] = None) -> AnalysisReport:
    """生成最终报告。company_name 默认按代码映射,未知代码用代码本身。
    rag_sources: RAG 检索到的知识库片段,供报告引用(防幻觉、可溯源)。"""
    company = COMPANY_NAMES.get(stock_code, stock_code)
    # 注意:用 list + join 拼接,避免"+"与 if/else 表达式优先级混淆导致拼接被截断
    parts = []
    parts.append(f"情感得分：{sentiment.score:.2f}(理由:{sentiment.reason})" if sentiment else "情感得分：无")
    parts.append(f"技术面解读：{technical_analysis or '无'}")
    parts.append(f"风险等级：{risk.risk_level if risk else '未知'}")
    parts.append(f"风险点：{('、'.join(risk.risks)) if risk else '无'}")
    parts.append(f"公司名称：{company}")
    # RAG 知识库内容:拼入 Prompt 并要求引用(若检索到)
    if rag_sources:
        parts.append("以下是检索到的知识库内容(来自公司财报),写报告时可参考,数据须与输入一致:")
        for i, src in enumerate(rag_sources, 1):
            parts.append(f"[知识库{i}] {src}")
        parts.append("要求:引用知识库数据时在对应处标注『来源:知识库』;知识库内容与输入冲突时以输入数据为准。")
    user_prompt = "\n".join(parts)

    if client.provider == "dify":
        # 走 dify 报告生成应用(输出变量 report)
        from ..services.dify import call_workflow
        out = call_workflow("report", {
            "sentiment_score": str(sentiment.score) if sentiment else "0.5",
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
        rag_sources=rag_sources or [],
    )
    logger.info("报告生成完成: %d 字符", len(report))
    return result
