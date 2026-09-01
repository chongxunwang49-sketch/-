"""
统一异常处理类(步骤11:高可用/降级思维)

设计思路:
- 为整个多智能体系统定义异常层级,让 LangGraph 的节点能精确捕获"哪一步失败了"。
- 分层:基类 StockAgentError -> 按环节细分。
- 与降级策略配合:节点捕获这些异常后,在 State 里打降级标记,
  Conditional Edge 据此跳过/降级某个环节,保证"一个 Agent 挂了系统不崩"。
"""
from typing import Optional


class StockAgentError(Exception):
    """系统统一异常基类。任何环节抛的异常都应能向上归到这一类。"""

    def __init__(self, message: str, *, stage: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(message)
        self.stage = stage      # 出错的环节名(如 collect/sentiment/technical/risk/report)
        self.detail = detail    # 原始异常细节,便于日志定位
        self.degraded = False   # 是否已降级(节点捕获后置 True)

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.stage:
            parts.append(f"[环节:{self.stage}]")
        if self.detail:
            parts.append(f"[详情:{self.detail}]")
        return " ".join(parts)


class DataCollectionError(StockAgentError):
    """数据采集环节异常(AKShare/爬虫全挂等)"""


class LLMCallError(StockAgentError):
    """LLM 调用异常(超时/后端不可用/输出非法)。是降级链中最常见的触发点。"""


class AgentStepError(StockAgentError):
    """某个 Agent 步骤的封装异常:被 LangGraph 节点捕获并转为降级标记。"""
