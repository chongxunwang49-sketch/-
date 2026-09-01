"""
情感分析 Agent(步骤8)
输入:新闻列表 -> 输出:情感得分 0-1 + 理由(SentimentResult)
支持 dify 后端(用户搭建的情感分析应用)与本地 LLM 两种路径。
"""
import logging
from typing import List, Optional

from ..schemas import NewsItem, SentimentResult
from .llm import LLMClient, LLMError, extract_json
from .prompts import SENTIMENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def run_sentiment_agent(news_items: List[NewsItem], client: LLMClient,
                        stock_code: str = "600519") -> SentimentResult:
    """
    对一批新闻做情感分析,返回加权情感得分。
    - 单条新闻先各自打分,再按条数平均(避免某条重磅新闻被稀释/放大,这里用简单平均)。
    - 新闻为空时直接返回中性 0.5,不让下游因无输入而崩溃。
    """
    if not news_items:
        logger.warning("情感分析:没有新闻输入,返回中性 0.5")
        return SentimentResult(stock_code=stock_code, score=0.5,
                               reason="无新闻输入,默认中性", source=client.provider)

    scores, reasons = [], []
    for item in news_items:
        result = _analyze_one(item, client, stock_code)
        # 回填单条新闻得分,供前端"情绪时间线"绘制逐条情感(不改业务判断,仅补充输出)
        item.sentiment_score = result.score
        scores.append(result.score)
        reasons.append(result.reason)

    avg_score = sum(scores) / len(scores)
    combined_reason = "；".join(reasons[:3])
    logger.info("情感分析完成: %d 条新闻, 平均得分 %.2f", len(news_items), avg_score)
    return SentimentResult(
        stock_code=stock_code,
        score=round(avg_score, 4),
        reason=combined_reason,
        source=client.provider,
    )


def _analyze_one(item: NewsItem, client: LLMClient, stock_code: str) -> SentimentResult:
    """分析单条新闻"""
    user_prompt = f"请分析以下新闻的情绪:\n{item.to_llm_text()}"
    try:
        if client.provider == "dify":
            # 走 dify 情感分析应用(输出变量 news_result,JSON 文本)
            from ..services.dify import call_workflow
            out = call_workflow("sentiment", {"news_text": f"{item.title}\n{item.content}"})
            data = extract_json(str(out.get("news_result", "")))
            score = float(data.get("score", 0.5))
            reason = str(data.get("reason", ""))
        else:
            text = client.complete(SENTIMENT_SYSTEM_PROMPT, user_prompt)
            data = extract_json(text)
            score = float(data.get("score", 0.5))
            reason = str(data.get("reason", ""))
        return SentimentResult(stock_code=stock_code, score=score, reason=reason,
                               source=client.provider)
    except (LLMError, ValueError, KeyError) as e:
        # 单条失败不影响整体:返回中性,记日志
        logger.warning("单条新闻情感分析失败(%s),返回中性: %s", e, item.title[:30])
        return SentimentResult(stock_code=stock_code, score=0.5,
                               reason="分析异常,默认中性", source=client.provider)
