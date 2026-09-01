# 多智能体股票分析系统 - 后端镜像(步骤15)
# 基于 python:3.11-slim(与本地 pytorch 环境一致,保证依赖兼容)
FROM python:3.11-slim

WORKDIR /app

# 先拷贝依赖并安装(利用 Docker 层缓存:代码改动不用重新装依赖)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝项目代码
COPY backend ./backend
COPY scripts ./scripts
COPY frontend ./frontend
COPY data ./data

ENV PYTHONPATH=/app
EXPOSE 8000

# 启动 FastAPI 后端(LLM 走宿主机的 Ollama,见 docker-compose 的 OLLAMA_BASE_URL)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
