"""
行情采集脚本:AKShare 获取个股日线数据并入库(StockPrice 表)

核心:多级降级策略(自主制作)+ AI Coding 实现
- Level-1 主数据源:AKShare(东财通道),失败后指数退避重试 3 次
- Level-2 备用数据源:新浪财经(akshare stock_zh_a_daily 通道)
- Level-3 最终兜底:本地 Mock 数据生成器,保障系统不崩溃
- DATA_SOURCE 标记真实数据来源(real/backup/mock),供下游(报告生成)判断
- 入库幂等:同一股票同一日期已有记录则跳过,可重复运行

直接运行: python scripts/fetch_stock_data.py
"""
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak  # noqa: E402
from backend.models import StockPrice  # noqa: E402
from backend.models import engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

# 配置结构化日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SessionLocal = sessionmaker(bind=engine)

# 多级降级策略:定义数据来源标记,方便下游判断是真实数据还是 Mock 数据
DATA_SOURCE = "real"  # real, backup, mock


def _save_to_db(df: pd.DataFrame, session: Session | None = None) -> int:
    """清洗数据并批量存入数据库(幂等:已存在的 (stock_code, date) 自动跳过)"""
    if df.empty:
        return 0
    stock_code = str(df["stock_code"].iloc[0])

    # 清洗:只取表字段、去空值、规整类型
    cols = ["date", "open_price", "close_price", "high_price", "low_price", "volume"]
    df = df[cols].dropna()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["open_price"] = df["open_price"].astype(float)
    df["close_price"] = df["close_price"].astype(float)
    df["high_price"] = df["high_price"].astype(float)
    df["low_price"] = df["low_price"].astype(float)
    df["volume"] = df["volume"].astype(int)

    objects = [
        StockPrice(
            stock_code=stock_code,
            date=row.date,
            open_price=row.open_price,
            close_price=row.close_price,
            high_price=row.high_price,
            low_price=row.low_price,
            volume=row.volume,
        )
        for row in df.itertuples(index=False)
    ]

    # 幂等去重:库中已有的日期不再插入
    dates = [obj.date for obj in objects]
    with SessionLocal() as s:
        existing = {
            d for (d,) in s.query(StockPrice.date)
            .filter(StockPrice.stock_code == stock_code, StockPrice.date.in_(dates))
            .all()
        }
    fresh = [obj for obj in objects if obj.date not in existing]

    # 批量入库(bulk_save_objects 高性能提交)
    if fresh:
        if session is not None:
            session.bulk_save_objects(fresh)
            session.commit()
        else:
            with SessionLocal() as s:
                s.bulk_save_objects(fresh)
                s.commit()
        logger.info("入库 %d 条行情记录(跳过 %d 条重复)", len(fresh), len(objects) - len(fresh))
    return len(fresh)


def _fetch_from_akshare(stock_code: str, days: int) -> pd.DataFrame:
    """Level-1 主数据源:AKShare(东财通道),近 N 天日线"""
    logger.info("尝试 [Level-1] 主数据源 AKShare 拉取 %s...", stock_code)
    end = date.today()
    start = end - timedelta(days=days)
    df = ak.stock_zh_a_hist(symbol=stock_code, period="daily",
                            start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                            adjust="qfq")
    if df is None or df.empty:
        raise ValueError("AKShare 返回数据为空")
    # 重命名列以匹配数据库
    df = df.rename(columns={"日期": "date", "开盘": "open_price", "收盘": "close_price",
                            "最高": "high_price", "最低": "low_price", "成交量": "volume"})
    df["stock_code"] = stock_code
    return df


def _fetch_from_backup(stock_code: str, days: int) -> pd.DataFrame:
    """Level-2 备用数据源:新浪财经(akshare 新浪通道)"""
    logger.warning("触发 [Level-2] 降级:尝试备用接口(新浪财经)...")
    end = date.today()
    start = end - timedelta(days=days)
    # 新浪接口需要市场前缀:6 开头为上交所(sh),其余按深交所(sz)
    prefix = "sh" if stock_code.startswith("6") else "sz"
    df = ak.stock_zh_a_daily(symbol=f"{prefix}{stock_code}",
                             start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                             adjust="qfq")
    if df is None or df.empty:
        raise ConnectionError("备用接口返回数据为空")
    # 新浪列名与东财不同,统一映射;成交量单位:股 → 手(与主源保持一致)
    df = df.rename(columns={"open": "open_price", "high": "high_price",
                            "low": "low_price", "close": "close_price", "volume": "volume"})
    df["volume"] = df["volume"] // 100
    df["stock_code"] = stock_code
    return df


def _fetch_mock_data(stock_code: str, days: int) -> pd.DataFrame:
    """Level-3 最终兜底:本地 Mock 数据生成器,保障系统不崩溃"""
    logger.critical("触发 [Level-3] 最终兜底:使用本地 Mock 数据生成器,保障系统不崩溃!")
    global DATA_SOURCE
    DATA_SOURCE = "mock"
    # 生成符合 Schema 的假数据
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days).strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates,
        "open_price": np.random.uniform(1700, 1800, days),
        "close_price": np.random.uniform(1700, 1800, days),
        "high_price": np.random.uniform(1800, 1900, days),
        "low_price": np.random.uniform(1600, 1700, days),
        "volume": np.random.randint(10000, 50000, days),
    })
    df["stock_code"] = stock_code
    return df


def _detect_market(stock_code: str) -> str:
    """按代码格式识别市场:a=A股(6位数字) hk=港股(5位数字) us=美股(字母)"""
    code = str(stock_code).strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return "a"
    if code.isdigit():
        return "hk" if len(code) == 5 else "a"
    return "us"


def _fetch_hk_us(stock_code: str, days: int) -> pd.DataFrame:
    """港股/美股日线(东财通道,第二批复支持)"""
    code = stock_code.strip().upper()
    end = date.today()
    start = end - timedelta(days=days)
    try:
        import akshare as ak
        df = ak.stock_hk_hist(symbol=code, period="daily",
                              start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                              adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open_price", "收盘": "close_price",
                                    "最高": "high_price", "最低": "low_price", "成交量": "volume"})
            df["stock_code"] = code
            return df
        # 美股
        df = ak.stock_us_hist(symbol=code, period="daily",
                              start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                              adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "开盘": "open_price", "收盘": "close_price",
                                    "最高": "high_price", "最低": "low_price", "成交量": "volume"})
            df["stock_code"] = code
            return df
    except Exception:
        pass
    raise ConnectionError(f"{code} 港股/美股数据不可用")


def fetch_stock_with_degradation(stock_code: str = "600519", days: int = 90) -> dict:
    """
    带多级降级和重试机制的主采集函数(核心亮点)
    返回: {"status": "success"|"degraded", "source": "real"|"backup"|"mock", "rows": 入库条数, ...}
    第二批:支持 港股(5位数字)/美股(字母) 多市场。
    """
    global DATA_SOURCE
    DATA_SOURCE = "real"  # 每次采集复位标记,防止上次 mock 状态污染本次结果

    # 多市场:港股/美股走专用通道(失败直接 Mock,不再回退 A股通道)
    if _detect_market(stock_code) in ("hk", "us"):
        try:
            df = _fetch_hk_us(stock_code, days)
            DATA_SOURCE = "real"
            rows = _save_to_db(df, session=None)
            return {"status": "success", "source": DATA_SOURCE, "rows": rows, "market": "hk/us"}
        except Exception as e:
            logger.error("港股/美股采集失败: %s", e)
            df = _fetch_mock_data(stock_code, days)
            rows = _save_to_db(df, session=None)
            return {"status": "degraded", "source": "mock", "rows": rows, "message": "港股/美股不可用,输出模拟数据"}

    for attempt in range(3):  # 主通道带重试(指数退避)
        try:
            df = _fetch_from_akshare(stock_code, days)
            DATA_SOURCE = "real"
            rows = _save_to_db(df, session=None)
            return {"status": "success", "source": DATA_SOURCE, "rows": rows}
        except Exception as e:
            logger.error("Level-1 主源拉取失败: %s,等待 %d 秒进行重试...", e, 2 ** attempt)
            time.sleep(2 ** attempt)  # 指数退避,防止直接把服务器打挂

    # 主源彻底失败,走备用源
    try:
        df = _fetch_from_backup(stock_code, days)
        DATA_SOURCE = "backup"
        rows = _save_to_db(df, session=None)
        return {"status": "success", "source": DATA_SOURCE, "rows": rows}
    except Exception as e:
        logger.error("Level-2 备用源拉取失败: %s", e)

    # 备用源也失败,走最终兜底(Mock 数据)
    df = _fetch_mock_data(stock_code, days)
    rows = _save_to_db(df, session=None)

    # 向上抛出明确的降级状态
    return {"status": "degraded", "source": DATA_SOURCE, "rows": rows,
            "message": "系统已降级,输出为模拟数据"}


def fetch_stock_data(symbol: str = "600519", days: int = 90) -> dict:
    """
    采集入口(供主程序/LangGraph 调用):内部走三级降级链,返回状态字典。
    :param symbol: 股票代码,默认 600519(贵州茅台)
    :param days:   回看天数,默认 90(近 3 个月)
    """
    start_time = time.perf_counter()
    result = fetch_stock_with_degradation(symbol, days)
    elapsed = time.perf_counter() - start_time
    logger.info("fetch_stock_data 完成: status=%s, source=%s, rows=%s, 耗时 %.2f 秒",
                result.get("status"), result.get("source"), result.get("rows"), elapsed)
    return result


if __name__ == "__main__":
    fetch_stock_data()
