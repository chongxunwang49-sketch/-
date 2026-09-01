"""
事件驱动 Agent(第四批)

基于新闻/公告(NewsItem 列表)识别重大事件及其方向(0-1)。
新闻为空时返回中性;LLM 失败降级中性。
"""
import logging
from typing import List

from ..schemas import EventResult, NewsItem
from .llm import LLMClient, LLMError, extract_json
from .prompts import EVENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def run_event_agent(news_items: List[NewsItem], client: LLMClient,
                    stock_code: str) -> EventResult:
    if not news_items:
        logger.warning("[event] 无新闻输入,返回中性")
        return EventResult(stock_code=stock_code, score=0.5,
                           events=[], summary="无新闻数据,中性")

    news_txt = "\n".join(n.to_llm_text() for n in news_items[:10])
    user_prompt = f"股票:{stock_code}\n近期新闻:\n{news_txt}"
    try:
        out = extract_json(client.complete(EVENT_SYSTEM_PROMPT, user_prompt))
        events = [str(e) for e in out.get("events", [])[:3]]
        return EventResult(stock_code=stock_code,
                           score=max(0.0, min(1.0, float(out.get("score", 0.5)))),
                           events=events, summary=str(out.get("summary", "")))
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("[event] LLM 失败,降级中性: %s", e)
        return EventResult(stock_code=stock_code, score=0.5,
                           events=[], summary="事件分析暂不可用")
