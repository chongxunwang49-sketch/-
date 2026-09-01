"""
Pydantic 数据模型 —— 多智能体之间的"通用语言"(步骤6)

设计思想:
- 多智能体系统里,Agent 之间如何通信?答:通过共享的数据结构(本文件)。
- 每个 Agent 的输入/输出都严格用 Pydantic 模型约束:
  情感分析 Agent 输入 NewsItem、输出 SentimentResult;
  技术分析 Agent 输入行情、输出 TechnicalIndicators;
  风险评估 Agent 输入 SentimentResult+TechnicalIndicators、输出 RiskAssessment;
  报告生成 Agent 汇总全部、输出 AnalysisReport。
- 好处:①字段类型强校验,坏数据进不来;②后续 LangGraph 的 State 直接复用这些模型;
  ③Dify 后端的 JSON 输出也能被这些模型解析校验。
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class NewsItem(BaseModel):
    """一条新闻(情感分析 Agent 的输入)"""

    stock_code: str = Field(description="关联股票代码,如 600519")
    title: str = Field(description="新闻标题")
    content: str = Field(default="", description="新闻正文/摘要")
    publish_time: Optional[datetime] = Field(default=None, description="发布时间")
    source: Optional[str] = Field(default=None, description="新闻来源")
    sentiment_score: Optional[float] = Field(
        default=None,
        description="单条新闻的情感得分 0-1(由情感分析 Agent 回填,用于前端情绪时间线)",
    )

    def to_llm_text(self) -> str:
        """把一条新闻转成给 LLM 看的紧凑文本"""
        return f"[{self.publish_time or '未知时间'} {self.source or '未知来源'}] {self.title}\n{self.content}"


class TechnicalIndicators(BaseModel):
    """技术指标(技术分析 Agent 的输出 / 风险评估 Agent 的输入)"""

    stock_code: str = Field(description="股票代码")
    latest_date: date = Field(description="指标计算的最近交易日")
    close_price: float = Field(description="最新收盘价")
    pct_change: Optional[float] = Field(default=None, description="最近一日涨跌幅(%)")
    ma5: Optional[float] = Field(default=None, description="5日均线")
    ma10: Optional[float] = Field(default=None, description="10日均线")
    ma20: Optional[float] = Field(default=None, description="20日均线")
    rsi14: Optional[float] = Field(default=None, description="RSI(14)")
    macd_dif: Optional[float] = Field(default=None, description="MACD DIF")
    macd_dea: Optional[float] = Field(default=None, description="MACD DEA")
    macd_hist: Optional[float] = Field(default=None, description="MACD 柱")
    volume: Optional[int] = Field(default=None, description="最新成交量(手)")

    def to_llm_text(self) -> str:
        """把技术指标转成给 LLM 看的文本(技术解读 Agent 的输入)"""
        parts = [
            f"股票:{self.stock_code}",
            f"最近交易日:{self.latest_date}",
            f"收盘价:{self.close_price:.2f}元",
        ]
        if self.pct_change is not None:
            parts.append(f"涨跌幅:{self.pct_change:+.2f}%")
        if self.ma5 is not None:
            parts.append(f"MA5:{self.ma5:.2f}")
        if self.ma10 is not None:
            parts.append(f"MA10:{self.ma10:.2f}")
        if self.ma20 is not None:
            parts.append(f"MA20:{self.ma20:.2f}")
        if self.rsi14 is not None:
            parts.append(f"RSI14:{self.rsi14:.2f}")
        if self.macd_dif is not None and self.macd_dea is not None:
            parts.append(f"MACD:DIF={self.macd_dif:.3f},DEA={self.macd_dea:.3f},柱={self.macd_hist:.3f}")
        if self.volume is not None:
            parts.append(f"成交量:{self.volume}手")
        return "、".join(parts)


class SentimentResult(BaseModel):
    """情感分析结果(情感分析 Agent 的输出)"""

    stock_code: str = Field(description="股票代码")
    score: float = Field(description="情感得分 0-1:0极度利空,1极度利好,0.5中性")
    reason: str = Field(default="", description="一句话理由")
    source: str = Field(default="", description="实际使用的 LLM 后端(ollama/deepseek/dify)")

    @field_validator("score")
    @classmethod
    def _check_score(cls, v: float) -> float:
        """得分必须落在 [0,1],越界则钳制(防 LLM 输出 1.2 之类的脏数据)"""
        if v < 0:
            return 0.0
        if v > 1:
            return 1.0
        return v


class RiskAssessment(BaseModel):
    """风险评估结果(风险评估 Agent 的输出)"""

    stock_code: str = Field(description="股票代码")
    risk_level: str = Field(description="风险等级:低/中/高")
    risks: List[str] = Field(default_factory=list, description="风险点列表(2-3条)")
    summary: str = Field(default="", description="一句话总结")

    @field_validator("risk_level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        """风险等级只允许 低/中/高,否则归为 中"""
        return v if v in {"低", "中", "高"} else "中"


class AnalysisReport(BaseModel):
    """完整分析报告(报告生成 Agent 的输出 / 整个工作流的最终产物)"""

    stock_code: str = Field(description="股票代码")
    company_name: str = Field(description="公司名称")
    sentiment: Optional[SentimentResult] = Field(default=None, description="情感分析结果")
    technical_analysis: Optional[str] = Field(default=None, description="技术面解读文本")
    risk: Optional[RiskAssessment] = Field(default=None, description="风险评估结果")
    report: str = Field(default="", description="最终报告(Markdown)")
    data_source: str = Field(default="real", description="行情数据来源标记:real/backup/mock")
    rag_sources: List[str] = Field(default_factory=list, description="报告引用的知识库片段(溯源/防幻觉)")
