"""
步骤14-测试场景④:风险评估规则兜底
LLM 不可用时的确定性降级:情感极空 -> 高风险。
"""
from backend.agents.risk import _rule_based_fallback
from backend.schemas import SentimentResult


def test_rule_fallback_high_when_very_negative():
    risk = _rule_based_fallback(
        SentimentResult(stock_code="600519", score=0.2), None, "600519")
    assert risk.risk_level == "高"


def test_rule_fallback_low_when_very_positive():
    risk = _rule_based_fallback(
        SentimentResult(stock_code="600519", score=0.9), None, "600519")
    assert risk.risk_level == "低"


def test_rule_fallback_medium_when_neutral():
    risk = _rule_based_fallback(
        SentimentResult(stock_code="600519", score=0.5), None, "600519")
    assert risk.risk_level == "中"


def test_rule_fallback_upgrades_on_bearish_technical():
    """技术面提到'空头'时,风险等级至少升到高"""
    risk = _rule_based_fallback(
        SentimentResult(stock_code="600519", score=0.8), "当前呈空头排列", "600519")
    assert risk.risk_level == "高"
