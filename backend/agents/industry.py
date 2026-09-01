"""
行业分析 Agent(第四批)

- 行业/对标公司来自预置映射表(stock_meta.INDUSTRY_MAP),零网络依赖
- run_industry_agent:LLM 结合行业常识评估景气度与竞争地位(0-1)
"""
import logging

from ..schemas import IndustryResult
from ..services import stock_meta
from .llm import LLMClient, LLMError, extract_json
from .prompts import INDUSTRY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def run_industry_agent(stock_code: str, client: LLMClient) -> IndustryResult:
    industry, peers = stock_meta.lookup_industry(stock_code)
    peers_txt = "、".join(peers) if peers else "无"
    user_prompt = (f"股票:{stock_code}({stock_meta.lookup_name(stock_code)})\n"
                   f"所属行业:{industry}\n对标公司:{peers_txt}")
    try:
        out = extract_json(client.complete(INDUSTRY_SYSTEM_PROMPT, user_prompt))
        return IndustryResult(stock_code=stock_code,
                              score=max(0.0, min(1.0, float(out.get("score", 0.5)))),
                              industry=industry, peers=peers,
                              summary=str(out.get("summary", "")))
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("[industry] LLM 失败,降级中性: %s", e)
        return IndustryResult(stock_code=stock_code, score=0.5,
                              industry=industry, peers=peers, summary="行业分析暂不可用")
