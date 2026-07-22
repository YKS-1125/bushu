# 🐳 Dockerfile —— Railway 用它构建整个应用（前端 + 后端打进同一镜像）
# 构建上下文 = 项目根目录（林小禾AI项目_完整迁移）
FROM python:3.11-slim

WORKDIR /app

# 系统依赖：部分科学计算包（scikit-learn / onnxruntime）编译时可能需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 先只复制依赖清单并安装 —— 利用 Docker 层缓存：requirements 没变就不重装
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir gunicorn==21.2.0

# 复制整个项目（backend + frontend）
COPY . .

# 【构建时重建 RAG 索引】读 knowledge/*.md → 生成 tfidf.pkl + chroma_db
# 放在构建阶段，避免把二进制产物提交进 Git 仓库
WORKDIR /app/backend
RUN python build_index.py

# 平台（Railway / Render）会注入 PORT 环境变量；本地默认 5000
EXPOSE 5000

# 生产级启动：gunicorn（sync worker + 多线程，支持流式响应）
# shell 形式写法，${PORT} 才能被环境变量替换
# workers 默认 1（适配 Render 免费版 512MB 内存，避免多进程各自加载向量库导致 OOM）；
#   流量大时可在平台设 WEB_CONCURRENCY 环境变量调高。threads 8 应对并发（本应用是 I/O 密集的流式请求）
CMD gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers ${WEB_CONCURRENCY:-1} --threads 8 --timeout 120 app:app
