"""
数据定时调度(第二批)

- APScheduler 后台调度,进程内运行(随 uvicorn 启动)
- 每日定时:为所有自选股刷新行情(三级降级)+ 新闻,保证数据新鲜
- 提供 start_scheduler() 供 main.py 在启动事件中调用(幂等,可重入)

设计:采集失败不抛出(任务内 try/except),避免调度器被异常打断。
"""
import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# 爬虫进度(管理后台轮询展示):{running,total,current,stock,message,updated_at}
COLLECT_PROGRESS = {
    "running": False, "total": 0, "current": 0,
    "stock": "", "message": "尚未采集", "updated_at": None,
}


def _collect_watchlist_stocks() -> int:
    """为所有自选股刷新行情与新闻,返回处理的股票数(最佳努力)。

    采集过程实时更新 COLLECT_PROGRESS,供 /admin/collect/status 轮询展示进度条。
    """
    try:
        from sqlalchemy import select

        from ..models import SessionLocal, Watchlist
        from scripts.fetch_news import fetch_news_data
        from scripts.fetch_stock_data import fetch_stock_with_degradation

        with SessionLocal() as session:
            codes = list(session.scalars(select(Watchlist.stock_code).distinct()).all())
        if not codes:
            codes = ["600519", "000858"]  # 无自选股时保底刷新

        COLLECT_PROGRESS.update({
            "running": True, "total": len(codes), "current": 0,
            "stock": codes[0] if codes else "", "message": "开始采集",
            "updated_at": time.time(),
        })
        done = 0
        for i, code in enumerate(codes, 1):
            COLLECT_PROGRESS.update({
                "current": i, "stock": code,
                "message": f"正在采集 {code} 行情+新闻", "updated_at": time.time(),
            })
            try:
                fetch_stock_with_degradation(code, days=90)
                fetch_news_data(stock_code=code, keyword=code)
                done += 1
                COLLECT_PROGRESS["message"] = f"{code} 采集成功"
            except Exception as e:
                logger.warning("定时采集 %s 失败: %s", code, e)
                COLLECT_PROGRESS["message"] = f"{code} 采集失败"
            COLLECT_PROGRESS["updated_at"] = time.time()
        COLLECT_PROGRESS.update({
            "running": False, "current": len(codes),
            "message": f"采集完成,共 {done}/{len(codes)} 只成功", "updated_at": time.time(),
        })
        logger.info("定时采集完成: 刷新 %d 只股票", done)
        return done
    except Exception as e:
        COLLECT_PROGRESS.update({"running": False, "message": f"采集异常:{e}"})
        logger.warning("定时采集任务异常: %s", e)
        return 0


def start_scheduler(hour: int = 8, minute: int = 30) -> None:
    """启动后台调度器(每日定时采集;幂等)"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # 错峰:8:30 触发;job 内自捕获异常
    _scheduler.add_job(_collect_watchlist_stocks, "cron", hour=hour, minute=minute,
                       id="daily_collect", max_instances=1, coalesce=True)
    _scheduler.add_job(_collect_watchlist_stocks, "interval", hours=6, id="interval_collect",
                       max_instances=1, coalesce=True, next_run_time=None)
    _scheduler.start()
    logger.info("数据调度器已启动: 每日 %02d:%02d + 每 6 小时采集自选股行情/新闻", hour, minute)
