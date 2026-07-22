# 林小禾 · 个人网站 + AI 助手

个人简历/作品集站点，内置一个基于 **DeepSeek + Flask + RAG** 的网站 AI 助手。
前后端同源部署：Flask 既托管静态前端页面，又提供 `/chat` 流式问答接口。

## 目录结构

```
林小禾AI项目/
├── backend/                 # Flask 后端
│   ├── app.py               # Web 服务：托管前端 + /chat 流式问答 + RAG + 限流
│   ├── build_index.py       # 读取 knowledge/*.md 重建向量索引（tfidf.pkl + chroma_db）
│   ├── step1_chat.py        # 命令行版对话（学习用）
│   ├── knowledge/           # AI 助手的知识库（Markdown），改这里即可改助手的回答依据
│   ├── requirements.txt     # Python 依赖
│   └── .env                 # DEEPSEEK_API_KEY（不入库）
├── frontend/
│   └── index.html           # 站点主页（单文件：结构 + 样式 + 脚本 + AI 聊天面板）
├── Dockerfile               # 前后端打进同一镜像；构建时执行 build_index.py 重建索引
└── render.yaml              # Render 部署蓝图
```

> 注：仓库根目录另有 `个人简历项目备份/index.html`，是本项目前端的**旧版快照（已废弃，静态版）**，仅作备份，不再维护。以本项目为唯一主线。

## 本地运行

```powershell
cd 林小禾AI项目/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

在 `backend/.env` 中填入密钥：

```
DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
```

首次运行前（或修改了 `knowledge/` 后）重建索引，然后启动：

```powershell
python build_index.py
python app.py
```

浏览器打开 http://127.0.0.1:5000 ，右下角悬浮按钮即为 AI 助手。

## 部署（Render）

1. 将本目录推到 GitHub 仓库。
2. Render → New + → Blueprint，连接仓库，自动读取 `render.yaml` 构建。
3. 在服务的 Environment 中填入 `DEEPSEEK_API_KEY`（`render.yaml` 标记为 `sync:false`，不写进仓库）。
4. 构建阶段 `Dockerfile` 会自动执行 `build_index.py` 重建向量索引，无需提交二进制产物。

> 免费实例内存 512MB、无访问会休眠；`WEB_CONCURRENCY` 固定为 1，避免多进程各自加载向量库导致 OOM。

## 技术要点

- **RAG**：`build_index.py` 用 TF-IDF 将 `knowledge/*.md` 向量化并存入 Chroma；`app.py` 的 `search_knowledge` 按问题检索最相关片段注入 Prompt，答案末尾以 `__REF__` 回传引用编号，前端渲染「参考了 [1][2]」。
- **流式输出**：`/chat` 用生成器 + `Response(stream_with_context(...))` 边收边吐，前端用 `ReadableStream` 逐字显示。
- **限流**：按 IP 的内存滑动窗口（默认 60s 内 10 次）。注意内存限流在多进程/重启后会失效，生产高流量场景建议改用 Redis。
- **安全**：`.env`、`.venv`、`tfidf.pkl`、`chroma_db/` 均已在 `.gitignore` 中忽略。

## 环境变量

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必填） | — |
| `PORT` | 服务端口 | 5000 |
| `WEB_CONCURRENCY` | gunicorn 进程数 | 1 |
| `ALLOWED_ORIGINS` | CORS 允许来源，逗号分隔；留空表示放行全部（仅开发用） | 空 |
