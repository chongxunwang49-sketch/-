"""
数据库模型定义:StockPrice(股票行情)与 NewsArticle(个股新闻)

设计说明:
- 行情与新闻是两类完全不同粒度的数据(行情一天一行、新闻一条一行),
  故分表存储,绝不混在一个表里
- StockPrice 建 (stock_code, date) 联合索引,支撑"按股票查某段时间行情"
  这类高频查询
- NewsArticle 建 stock_code 普通索引,支撑"按股票拉取新闻"查询

建表方式(需 PostgreSQL 已启动):
    python backend/models.py
"""
import os
from datetime import date, datetime

from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 加载项目根目录下的 .env(文件不存在时自动使用下方默认值)
load_dotenv()

# ------------------------------------------------------------
# 数据库连接配置(PostgreSQL)
# ------------------------------------------------------------
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "stock_agent")

# 连接字符串:SQLAlchemy 方言 + psycopg2 驱动
DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# 全局引擎(懒连接,导入本模块时不会真正连库)
# pool_pre_ping=True: 连接被数据库端断开时自动重连,提升稳定性
engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类(Base.metadata.create_all 依赖它收集表定义)"""


class StockPrice(Base):
    """股票日行情表:一只股票一个交易日一行"""

    __tablename__ = "stock_price"

    # 联合索引:按 股票代码+日期 快速定位行情区间
    __table_args__ = (
        Index("ix_stock_price_code_date", "stock_code", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, comment="股票代码,如 600519")
    date: Mapped[date] = mapped_column(Date, nullable=False, comment="交易日期")
    open_price: Mapped[float] = mapped_column(Float, comment="开盘价")
    close_price: Mapped[float] = mapped_column(Float, comment="收盘价")
    high_price: Mapped[float] = mapped_column(Float, comment="最高价")
    low_price: Mapped[float] = mapped_column(Float, comment="最低价")
    volume: Mapped[int] = mapped_column(Integer, comment="成交量(手)")


class NewsArticle(Base):
    """个股新闻表:一条新闻一行,与行情表完全独立"""

    __tablename__ = "news_article"

    # 按股票代码拉新闻是情感分析的固定入口,建普通索引
    __table_args__ = (
        Index("ix_news_article_stock_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, comment="关联股票代码")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="新闻标题")
    content: Mapped[str] = mapped_column(Text, comment="新闻正文")
    publish_time: Mapped[datetime] = mapped_column(DateTime, comment="发布时间")
    source: Mapped[str] = mapped_column(String(50), comment="新闻来源,如:东方财富")


def create_tables() -> None:
    """按模型定义在 PostgreSQL 中建表(幂等,表已存在则跳过)"""
    Base.metadata.create_all(bind=engine)
    print("建表完成: stock_price(含 stock_code+date 联合索引)、news_article")


if __name__ == "__main__":
    create_tables()
