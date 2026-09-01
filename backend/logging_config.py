"""
结构化日志配置(步骤16)

输出 JSON 行日志,便于采集与监控关键指标:
- 每次 LLM 调用的 token 消耗与耗时
- 每个 Agent 的成败
- 采集数据源标记(real/backup/mock)

用法:
  from backend.logging_config import setup_logging
  setup_logging()
"""
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """把日志行格式化为单行 JSON,含可选 metrics 字段"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "metrics"):
            payload["metrics"] = record.metrics
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """统一 JSON 结构化日志(全局生效)"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def log_metrics(logger: logging.Logger, event: str, **metrics) -> None:
    """记录一条带指标的结构化日志(如 token/耗时/Agent 失败数)"""
    logger.info(event, extra={"metrics": metrics})
