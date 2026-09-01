"""
步骤14-测试场景①:数据模型校验
重点验证 Pydantic 对 LLM 脏输出的防御:
- 情感得分越界(>1 / <0)被钳制
- 风险等级非法值被归为"中"
"""
from backend.schemas import RiskAssessment, SentimentResult


def test_sentiment_score_clamped_high():
    """LLM 输出 1.5 时应钳制为 1.0(避免脏数据传播)"""
    r = SentimentResult(stock_code="600519", score=1.5)
    assert r.score == 1.0


def test_sentiment_score_clamped_low():
    """LLM 输出 -0.3 时应钳制为 0.0"""
    r = SentimentResult(stock_code="600519", score=-0.3)
    assert r.score == 0.0


def test_sentiment_score_normal_kept():
    r = SentimentResult(stock_code="600519", score=0.6)
    assert r.score == 0.6


def test_risk_level_valid():
    assert RiskAssessment(stock_code="600519", risk_level="高").risk_level == "高"


def test_risk_level_invalid_falls_to_medium():
    """LLM 输出非法风险等级时归为'中'(保守默认)"""
    r = RiskAssessment(stock_code="600519", risk_level="非常高")
    assert r.risk_level == "中"
