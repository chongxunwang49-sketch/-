"""
第四批:新增 Agent 测试(基本面/估值/资金流向/行业/事件)

- 模型 score 钳制(0-1)
- 行业映射查询
- 事件 Agent 空新闻降级中性
- 各 Agent 在 LLM 失败时的降级(用抛异常的假 LLM)
"""
import pytest

from backend.schemas import EventResult, FundamentalResult, FundFlowResult, IndustryResult, ValuationResult
from backend.services import stock_meta


# ------------------------------------------------------------
# 模型 score 钳制
# ------------------------------------------------------------
def test_score_clamping():
    assert FundamentalResult(stock_code="x", score=1.3).score == 1.0
    assert ValuationResult(stock_code="x", score=-0.2).score == 0.0
    assert FundFlowResult(stock_code="x", score=0.8).score == 0.8
    assert IndustryResult(stock_code="x", score=1.1).score == 1.0
    assert EventResult(stock_code="x", score=-1.0).score == 0.0


# ------------------------------------------------------------
# 行业映射
# ------------------------------------------------------------
def test_industry_map():
    assert stock_meta.lookup_industry("600519") == ("白酒", ["五粮液", "泸州老窖", "山西汾酒"])
    ind, peers = stock_meta.lookup_industry("999999")
    assert ind == "未知" and peers == []


# ------------------------------------------------------------
# 事件 Agent:空新闻 -> 中性
# ------------------------------------------------------------
def test_event_agent_empty_news():
    from backend.agents.event import run_event_agent

    class _BrokenLLM:
        provider = "test"
        def complete(self, *a, **k):
            raise RuntimeError("no llm")

    r = run_event_agent([], _BrokenLLM(), "600519")
    assert r.score == 0.5
    assert r.events == []


# ------------------------------------------------------------
# 各 Agent:LLM 失败 -> 降级中性(不抛异常)
# ------------------------------------------------------------
class _FakeLLM:
    """complete 返回脏数据/或抛 LLMError 的假 LLM,用于测降级路径"""
    provider = "test"

    def __init__(self, mode="fail"):
        self.mode = mode

    def complete(self, *a, **k):
        if self.mode == "fail":
            from backend.agents.llm import LLMError
            raise LLMError("llm down")   # 模拟真实网络/超时失败
        return "not json at all"


def test_industry_agent_llm_fail_degrades():
    from backend.agents.industry import run_industry_agent
    r = run_industry_agent("600519", _FakeLLM("fail"))
    assert r.score == 0.5
    assert r.industry == "白酒"          # 行业来自映射表,不因 LLM 失败丢失


def test_industry_agent_llm_dirty_degrades():
    from backend.agents.industry import run_industry_agent
    r = run_industry_agent("600519", _FakeLLM("dirty"))
    assert r.score == 0.5


def test_fundamental_agent_degrades():
    from backend.agents.fundamental import run_fundamental_agent
    r = run_fundamental_agent("600519", _FakeLLM("fail"))
    assert r.score == 0.5
    assert r.summary


def test_valuation_agent_degrades():
    from backend.agents.valuation import run_valuation_agent
    r = run_valuation_agent("600519", _FakeLLM("fail"))
    assert r.score == 0.5


def test_flow_agent_degrades():
    from backend.agents.flow import run_flow_agent
    r = run_flow_agent("600519", _FakeLLM("fail"))
    assert r.score == 0.5
