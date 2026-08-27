"""
行情采集脚本:AKShare 获取个股日线数据并入库(StockPrice 表)

特性:
- 使用 akshare.stock_zh_a_hist 接口,默认抓取近 3 个月日线(前复权,保证技术指标连续)
- tenacity 重试机制(失败自动重试 3 次)
- 入库前清洗:去空值、类型规整(价格 Float、成交量 Integer、日期 Date)
- 幂等:同一股票同一日期已有记录则跳过,可重复运行不产生重复行
- SQLAlchemy Session + bulk_save_objects 批量提交

直接运行: python scripts/fetch_stock_data.py
"""
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak  # noqa: E402
from backend.models import StockPrice  # noqa: E402
from backend.models import engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SessionLocal = sessionmaker(bind=engine)

# 【待接入:异常降级策略(自主制作)】
# 若 AKShare 重试 3 次仍失败,你想切备用接口还是返回 Mock 数据?
# 在 _fallback_after_failure() 中实现你的策略,由 fetch_stock_data() 自动调用
FALLBACK_ENABLED = False


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def _fetch_from_akshare(symbol: str, start: str, end: str) -> pd.DataFrame:
    """调用 AKShare 日线接口(带自动重试)。日期格式:YYYYMMDD"""
    logger.info("调用 akshare.stock_zh_a_hist(symbol=%s, %s ~ %s)", symbol, start, end)
    return ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")


def _fallback_after_failure(symbol: str, start: str, end: str) -> pd.DataFrame:
    """【待接入】AKShare 完全失败后的降级:备用数据源或 Mock 数据"""
    logger.warning("AKShare 获取失败,当前降级策略未启用(FALLBACK_ENABLED=False)")
    return pd.DataFrame()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """清洗行情数据:映射中文列名、去空值、规整类型"""
    df = df.rename(columns={
        "日期": "date",
        "开盘": "open_price",
        "收盘": "close_price",
        "最高": "high_price",
        "最低": "low_price",
        "成交量": "volume",
    })
    df = df[["date", "open_price", "close_price", "high_price", "low_price", "volume"]]
    # 停牌等原因可能出现空值,直接剔除该行
    df = df.dropna(subset=["open_price", "close_price", "high_price", "low_price", "volume"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["volume"] = df["volume"].astype(int)
    df["open_price"] = df["open_price"].astype(float)
    df["close_price"] = df["close_price"].astype(float)
    df["high_price"] = df["high_price"].astype(float)
    df["low_price"] = df["low_price"].astype(float)
    return df


def fetch_stock_data(symbol: str = "600519", days: int = 90) -> int:
    """
    抓取某只股票近 N 天日线并批量入库,返回实际插入条数。
    :param symbol: 股票代码,默认 600519(贵州茅台)
    :param days:   回看天数,默认 90(近 3 个月)
    """
    start_time = time.perf_counter()
    end = date.today()
    start = end - timedelta(days=days)
    logger.info("开始抓取 %s 行情: %s ~ %s", symbol, start, end)

    # 1. 抓取(带重试;失败走降级策略)
    try:
        raw = _fetch_from_akshare(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    except Exception as e:
        logger.error("AKShare 重试 3 次后仍失败: %s", e)
        if FALLBACK_ENABLED:
            raw = _fallback_after_failure(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        else:
            raise
    if raw.empty:
        logger.warning("未获取到任何数据")
        return 0
    logger.info("抓取成功 %d 条原始记录", len(raw))

    # 2. 清洗并构造 ORM 对象
    clean = _clean(raw)
    logger.info("清洗后 %d 条有效记录", len(clean))
    objects = [
        StockPrice(
            stock_code=symbol,
            date=row.date,
            open_price=row.open_price,
            close_price=row.close_price,
            high_price=row.high_price,
            low_price=row.low_price,
            volume=row.volume,
        )
        for row in clean.itertuples(index=False)
    ]

    # 3. 幂等去重:库中已存在的 (stock_code, date) 不再插入
    dates = [obj.date for obj in objects]
    with SessionLocal() as session:
        existing = {
            d for (d,) in session.query(StockPrice.date)
            .filter(StockPrice.stock_code == symbol, StockPrice.date.in_(dates))
            .all()
        }
    fresh = [obj for obj in objects if obj.date not in existing]
    skipped = len(objects) - len(fresh)
    if skipped:
        logger.info("跳过已存在的 %d 条重复记录", skipped)

    # 4. 批量入库
    if fresh:
        with SessionLocal() as session:
            session.bulk_save_objects(fresh)
            session.commit()
        logger.info("插入 %d 条行情记录", len(fresh))

    elapsed = time.perf_counter() - start_time
    logger.info("fetch_stock_data 完成: 抓取 %d 条, 插入 %d 条, 跳过 %d 条, 耗时 %.2f 秒",
                len(raw), len(fresh), skipped, elapsed)
    return len(fresh)


if __name__ == "__main__":
    fetch_stock_data()
