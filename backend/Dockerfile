# backend Dockerfile（构建上下文 = 项目根目录，见 docker-compose.yml build.context）
# 产物目录：/app/backend、/app/scripts、/app/requirements.txt
FROM python:3.11-slim

WORKDIR /app

# 清华 pip 镜像加速（容器内下载依赖）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/

# 审核 R-33：非 root 运行（python:3.11-slim 无用户，创建 appuser 并授权工作目录）
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8006

# lifespan 自动执行幂等 migrations（首次启动建表）
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8006"]
