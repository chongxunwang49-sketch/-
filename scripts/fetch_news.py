"""
新闻爬虫脚本:抓取东方财富网关于某关键词的近期新闻并入库(NewsArticle 表)

流程:
1. 调用东方财富搜索接口获取新闻列表(标题/摘要/链接/发布时间/媒体)
2. requests + BeautifulSoup 逐条抓取正文,截取前 500 字
3. 正文抓取失败时降级用搜索摘要兜底(不中断整体流程)
4. SQLAlchemy Session + bulk_save_objects 批量入库,标题重复自动跳过

直接运行: python scripts/fetch_news.py
"""
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models import NewsArticle  # noqa: E402
from backend.models import engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SessionLocal = sessionmaker(bind=engine)

# 东方财富搜索接口(jsonp 返回)
SEARCH_API = "https://search-api-web.eastmoney.com/search/jsonp"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://so.eastmoney.com/",
}
CONTENT_LIMIT = 500  # 正文只存前 500 字
PAGE_SIZE = 10       # 抓取的新闻条数上限


def _build_search_params(keyword: str, page_size: int) -> dict:
    """构造东方财富搜索接口的请求参数"""
    return {
        "cb": "cb",
        "param": json.dumps({
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": page_size,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }, ensure_ascii=False),
    }


def _parse_jsonp(text: str) -> dict:
    """把 jsonp 响应(cb({...}))剥成 dict"""
    m = re.search(r"\((\{.*\})\)", text, re.S)
    if not m:
        raise ValueError("jsonp 响应格式异常")
    return json.loads(m.group(1))


def _search_news(keyword: str, page_size: int) -> list[dict]:
    """搜索新闻,返回 [{title, url, date, media, summary}]"""
    params = _build_search_params(keyword, page_size)
    resp = requests.get(SEARCH_API, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = _parse_jsonp(resp.text)
    items = []
    for item in data.get("result", {}).get("cmsArticleWebOld", []):
        items.append({
            "title": re.sub(r"<[^>]+>", "", item.get("title", "")).strip(),
            "url": item.get("url", ""),
            "date": item.get("date", ""),
            "media": item.get("mediaName", ""),
            "summary": re.sub(r"<[^>]+>", "", item.get("content", "")).strip(),
        })
    return [i for i in items if i["title"] and i["url"]]


def _parse_time(value: str) -> datetime | None:
    """兼容多种时间格式,解析失败返回 None"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def _fetch_article_body(url: str) -> str:
    """requests + BeautifulSoup 抓取正文(取最长文本区块的段落拼接)"""
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 东方财富正文常见容器,按文本长度取最长的那个
    candidates = ["#ContentBody", ".txtinfos", ".article-content", "article", "body"]
    best = ""
    for selector in candidates:
        node = soup.select_one(selector)
        if node:
            text = "\n".join(p.get_text(strip=True) for p in node.find_all("p"))
            if len(text) > len(best):
                best = text
    if not best:
        best = soup.get_text(" ", strip=True)
    return best.strip()


def fetch_news_data(stock_code: str = "600519", keyword: str = "茅台", limit: int = PAGE_SIZE) -> int:
    """
    抓取关键词相关新闻并批量入库,返回实际插入条数。
    :param stock_code: 关联股票代码,默认 600519
    :param keyword:    搜索关键词,默认 茅台
    :param limit:      抓取条数上限
    """
    start_time = time.perf_counter()
    logger.info("开始抓取新闻: 关键词=%s, 上限=%d 条", keyword, limit)

    # 1. 搜索获取新闻列表
    items = _search_news(keyword, limit)
    logger.info("搜索到 %d 条新闻", len(items))

    # 2. 逐条抓正文(失败用摘要兜底,不中断)
    objects = []
    body_ok = 0
    for it in items:
        try:
            body = _fetch_article_body(it["url"])
            if body:
                body_ok += 1
            else:
                logger.warning("正文为空,用摘要兜底: %s", it["title"][:30])
                body = it["summary"]
        except Exception as e:
            logger.warning("正文抓取失败(%s),用摘要兜底: %s", e, it["title"][:30])
            body = it["summary"]
        objects.append(NewsArticle(
            stock_code=stock_code,
            title=it["title"][:255],
            content=body[:CONTENT_LIMIT],
            publish_time=_parse_time(it["date"]),
            source=it["media"] or "东方财富",
        ))
    logger.info("正文抓取成功 %d/%d 条", body_ok, len(items))

    # 3. 幂等去重:标题已存在则跳过
    with SessionLocal() as session:
        existing = {
            t for (t,) in session.query(NewsArticle.title)
            .filter(NewsArticle.stock_code == stock_code).all()
        }
    fresh = [o for o in objects if o.title not in existing]
    skipped = len(objects) - len(fresh)
    if skipped:
        logger.info("跳过已存在的 %d 条重复新闻", skipped)

    # 4. 批量入库
    if fresh:
        with SessionLocal() as session:
            session.bulk_save_objects(fresh)
            session.commit()
        logger.info("插入 %d 条新闻记录", len(fresh))

    elapsed = time.perf_counter() - start_time
    logger.info("fetch_news_data 完成: 搜索 %d 条, 插入 %d 条, 跳过 %d 条, 耗时 %.2f 秒",
                len(items), len(fresh), skipped, elapsed)
    return len(fresh)


if __name__ == "__main__":
    fetch_news_data()
