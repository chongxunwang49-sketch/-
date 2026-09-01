# 多智能体股票分析系统

基于 **LangGraph 多智能体编排 + RAG 检索增强**的 A 股个股自动分析系统。输入股票代码,系统自动完成数据采集 → 技术分析 & 情感分析(并行) → 风险评估 → 报告生成,并以**专业投研终端**形式在前端展示:行情看板、交互式 K 线(均线/成交量/MACD/RSI)、Agent 流水线进度、结构化投资报告、RAG 数据溯源。

前端(Streamlit)采用"侧边栏控制面板 + 顶部行情概览 + 中部图表 + 底部多标签页"的专业看板布局,分析任务改为**异步轮询**(`POST /analyze` → 轮询 `/task/status` → 取 `/task/result`),避免长 HTTP 阻塞。

---

## 一、系统架构

```
┌────────────────────────────── 前端 Streamlit(:8501) ─────────────────────────────┐
│  输入股票代码 → 进度条(逐Agent) → K线图(Plotly) + 分析报告(Markdown)              │
└───────────────────────────────────┬──────────────────────────────────────────────┘
                                    │ SSE 流式进度 / 结果
┌────────────────────────────── 后端 FastAPI(:8000) ───────────────────────────────┐
│                       /analyze  /analyze/stream(SSE)                             │
│                                                                                  │
│   ┌─────────── LangGraph 状态机(graph/workflow.py) ────────────┐                 │
│   │  采集(collect)                                              │                 │
│   │   ├─▶ 技术分析(technical) ─┐                               │                 │
│   │   └─▶ 情感分析(sentiment) ─┼─▶ 风险评估(risk) ─▶ 报告(report)│  ← 并行fan-out  │
│   │        条件路由:新闻为空跳过情感 ────────────────────────── │                 │
│   └──────────────┬──────────────────────────────┬─────────────┘                 │
│                  │                              │                               │
│   ┌──────────────▼──────────┐   ┌───────────────▼──────────────┐                │
│   │  数据层:三级降级采集     │   │  LLM 层:可插拔后端           │                │
│   │  AKShare→新浪→Mock      │   │  ollama / deepseek / dify    │                │
│   │  + 东方财富新闻爬虫      │   │                              │                │
│   └──────────────┬──────────┘   └──────────────────────────────┘                │
│                  ▼                                                              │
│   PostgreSQL(行情/新闻)  ChromaDB(RAG向量库, bge 中文检索)                      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**核心设计理念:**
- **多智能体通信靠数据契约**:所有 Agent 的输入/输出由 Pydantic 模型(`backend/schemas.py`)严格约束,坏数据进不来。
- **模型可插拔**:`LLM_PROVIDER` 一行配置在 `ollama`(本地免费)/ `deepseek`(API)/ `dify`(可视化搭建)/ `dashscope`(阿里云百炼,OpenAI 兼容)间切换,架构上不留绑定。
- **高可用**:数据采集三级降级(主源→备用→Mock)+ 情感失败规则兜底,单个 Agent 挂了系统不崩。

---

## 一·五、后端 API(专业看板升级 + 用户体系第一批)

| 接口 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /auth/register` | 注册(用户名唯一 + 密码强度),成功即返回 token |
| `POST /auth/login` | 登录,返回 JWT |
| `GET /auth/me` | 当前用户信息(需 Bearer) |
| `PUT /user/profile` | 更新资料/改密码(需 Bearer) |
| `GET /user/history` | 我的分析历史(需 Bearer) |
| `GET/POST/DELETE /user/watchlist` | 自选股管理(需 Bearer) |
| `GET /market/indices` | 市场指数行情条(上证/深证/创业板/沪深300/恒生/标普,东财实时→新浪日线兜底) |
| `GET /stock/info?code=600519` | 基础信息(名称/现价/涨跌幅/技术指标快照) |
| `GET /stock/history?code=600519&range=3m` | K线历史(含 MA/MACD/RSI/BOLL 序列;`range=1m/3m/6m/1y/custom`) |
| `GET /stock/news?code=600519` | 个股新闻列表 |
| `POST /analyze` | 异步启动分析(需 Bearer,自动写入分析历史),`{stock_code, mode}` |
| `GET /task/status?task_id=...` | 轮询任务状态(各 Agent 阶段/耗时/降级标记) |
| `GET /task/result?task_id=...` | 最终报告 + 全部中间数据 + LLM token 统计 |
| `POST /analyze/sync`、`GET /analyze/stream` | 兼容旧接口 |

**异步工作流**:`POST /analyze` 立即返回 `task_id` → 后端 `TaskManager` 后台线程跑 LangGraph,消费 `graph.stream()` 事件流映射各 Agent 进度 → 前端每 ~1s 轮询 `/task/status`,完成后取 `/task/result`。
**用户体系**:bcrypt 密码散列 + JWT(HS256) 认证;首次启动自动创建管理员 `admin/admin123`(可用 `ADMIN_USERNAME/ADMIN_PASSWORD` 覆盖);`/analyze` 需登录,完成后写入该用户 `analysis_history`。
**分析模式**:`full` = 完整链路(采集→技术∥情感→风险→报告+RAG);`quick` = 跳过情感分析(更快)。

---

## 二、目录结构

```
stock-agent-system/
├── backend/
│   ├── main.py            # FastAPI: /analyze(同步) + /analyze/stream(SSE进度)
│   ├── models.py          # SQLAlchemy 模型(行情/新闻,含联合索引)
│   ├── schemas.py         # Pydantic 数据契约(多智能体通用语言)
│   ├── exceptions.py      # 统一异常层级(步骤11 降级骨架)
│   ├── logging_config.py  # 结构化 JSON 日志(Token/耗时/Agent失败)
│   ├── agents/            # 核心单智能体
│   │   ├── llm.py         #   LLM 调用层(ollama/deepseek/dify 可插拔)
│   │   ├── prompts.py     #   各 Agent System Prompt
│   │   ├── sentiment.py   #   情感分析 Agent
│   │   ├── technical.py   #   技术分析 Agent(指标计算+解读)
│   │   ├── risk.py        #   风险评估 Agent(含规则兜底)
│   │   └── report.py      #   报告生成 Agent
│   ├── services/
│   │   ├── task_manager.py # 异步任务管理(线程 + stream 事件 -> Agent 进度)
│   │   ├── stock_meta.py   # A股标的映射表(名称补全)
│   │   ├── auth.py         # 用户认证(bcrypt + JWT + 密码强度)
│   │   └── history_service.py # 分析历史落库 + 综合评分
│   └── graph/workflow.py  # LangGraph 编排(并行+条件路由+降级)
├── frontend/              # Streamlit 专业投研终端(导航壳 + 多页面)
│   ├── app.py             # 入口:登录门禁 + 侧边栏导航 + 全局流水线轮询 + 页面路由
│   ├── auth_ui.py         # 登录/注册页(暗色粒子动画 + 密码强度)
│   ├── api_client.py      # 后端 API 客户端(认证 + 异步轮询)
│   ├── data_layer.py      # 共享数据缓存(行情/指数,带 TTL)
│   ├── stock_map.py       # A股标的映射(前端副本)
│   ├── theme.py           # 暗色/亮色主题 + 全局 CSS
│   ├── components/        # 图表/流水线/报告卡片组件
│   └── page_views/        # 页面:行情看板 / 深度分析 / 自选股 / 历史记录
├── .streamlit/config.toml # Streamlit 暗色主题
├── scripts/               # 采集与建库脚本
│   ├── fetch_stock_data.py # 行情三级降级采集
│   ├── fetch_news.py       # 东方财富新闻爬虫
│   ├── build_vector_store.py # RAG 建库(500/50分块+向量化)
│   └── view_tables.py      # 数据库表查看器(开发工具)
├── data/rag_docs/         # RAG 语料(贵州茅台年度报告 PDF)
├── tests/                 # pytest(15 用例)
├── requirements.txt / Dockerfile / docker-compose.yml
└── .env.example           # 环境配置模板(复制为 .env)
```

---

## 三、快速开始

### 方式 A:本地运行(开发)

**前置**:Python 3.11、PostgreSQL(本机或容器)、Ollama(qwen2.5:3b + bge 模型)。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境
cp .env.example .env        # 按需改 LLM_PROVIDER、数据库等

# 3. 建表 + 采集 + RAG(可选)
python backend/models.py            # 建表
python scripts/fetch_stock_data.py  # 采集行情
python scripts/fetch_news.py        # 采集新闻
python scripts/build_vector_store.py # 构建 RAG 库

# 4. 启动后端 + 前端
uvicorn backend.main:app --port 8000
streamlit run frontend/app.py
```

浏览器打开 `http://localhost:8501`,输入 `600519` 点开始分析。

### 方式 B:Docker 一键部署

```bash
docker compose up -d --build
# 后端:   http://localhost:8000/health 确认就绪
# 前端:   http://localhost:8501         专业投研终端
```
(LLM 走宿主机 Ollama,容器经 `host.docker.internal:11434` 访问;
`docker-compose.yml` 含 4 个服务:`postgres` + `chroma` + `backend` + `frontend`)

---

## 四、dify 接入(可选,作 Agent 的 LLM 后端)

在 dify 平台搭建 4 个工作流应用(情感/技术/风险/报告),详见 `dify的详细操作.md`。搭好后:

```env
LLM_PROVIDER=dify
DIFY_BASE_URL=http://localhost/v1
DIFY_APP_ID=app-xxxxxx
DIFY_API_KEY=app-xxxxx.xxxx
```

---

## 五、测试

```bash
pytest tests/ -v     # 15 个用例:模型校验/指标计算/降级链/规则兜底
```

---

## 六、技术栈

| 领域 | 选型 |
|---|---|
| 多智能体编排 | LangGraph(状态机,并行 fan-out + 条件路由) |
| LLM | 本地 Ollama(qwen2.5:3b)/ DeepSeek API / dify(可插拔) |
| 向量检索 | ChromaDB + BGE(bge-large-zh-v1.5 本地平替) |
| 数据 | AKShare(三级降级)、东方财富爬虫、PostgreSQL |
| 后端/前端 | FastAPI(SSE)、Streamlit + Plotly |
| 工程化 | pytest、Docker Compose、结构化 JSON 日志 |

---

## 七、免责声明

本系统仅用于学习与技术演示,不构成任何投资建议。
