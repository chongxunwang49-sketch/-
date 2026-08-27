"""
数据库表查看器(开发工具,非正式前端)
- 实时连接 PostgreSQL,展示 stock_price / news_article 两张表
- 上半部分:表结构(字段、类型、可空、索引)
- 下半部分:表内数据预览(空表显示为空,步骤4 采集入库后刷新即可看到数据)

启动: streamlit run scripts/view_tables.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import inspect, text

# 把项目根目录加入模块搜索路径,保证能导入 backend.models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models import engine  # noqa: E402

st.set_page_config(page_title="股票分析系统 - 数据库表查看器", layout="wide")
st.title("🗄️ 数据库表查看器(PostgreSQL / stock_agent)")
st.caption("表结构来自 SQLAlchemy 模型,数据为实时查询。步骤4 采集入库后刷新页面即可看到行情与新闻数据。")

try:
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names())
    st.success(f"✅ 数据库连接正常,共 {len(table_names)} 张表:{', '.join(table_names)}")

    for tname in table_names:
        st.header(f"📋 表:{tname}")

        # --- 表结构 ---
        columns = inspector.get_columns(tname)
        schema_df = pd.DataFrame([
            {
                "字段名": c["name"],
                "类型": str(c["type"]),
                "可空": "是" if c.get("nullable") else "否",
                "默认值": c.get("default"),
                "注释": c.get("comment"),
            }
            for c in columns
        ])
        indexes = inspector.get_indexes(tname)
        index_info = "; ".join(
            f"{idx['name']}({', '.join(idx['column_names'])})" + (" [唯一]" if idx.get("unique") else "")
            for idx in indexes
        ) or "无"
        pk = inspector.get_pk_constraint(tname).get("constrained_columns", [])

        st.markdown(f"**主键:** {', '.join(pk) or '无'}　|　**索引:** {index_info}")
        st.subheader("表结构")
        st.dataframe(schema_df, use_container_width=True, hide_index=True)

        # --- 数据预览 ---
        with engine.connect() as conn:
            total = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
        st.subheader(f"数据预览(共 {total} 行,最多显示 50 行)")
        if total:
            preview_df = pd.read_sql(f'SELECT * FROM "{tname}" ORDER BY id LIMIT 50', engine)
            st.dataframe(preview_df, use_container_width=True)
        else:
            st.info("表当前为空。运行 scripts/fetch_stock_data.py 与 scripts/fetch_news.py 后可在此查看数据。")
        st.divider()

except Exception as e:
    st.error(f"❌ 数据库连接失败:{e}")
    st.markdown("请确认 PostgreSQL 容器已启动:`docker start stock-agent-postgres`")
