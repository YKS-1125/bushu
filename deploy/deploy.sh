#!/usr/bin/env bash
# ============================================================
# 林小禾 AI 网站 —— 国内云服务器一键部署脚本（Ubuntu 22.04）
# ------------------------------------------------------------
# 用法：
#   1. 连上服务器后，先设置好 API 密钥（二选一）：
#        方式A（推荐）：export DEEPSEEK_API_KEY="你的密钥"
#        方式B：不设置，脚本运行到一半会提示你手动粘贴
#   2. 运行：  bash deploy.sh
#
# 脚本做了什么：
#   ① 安装 Docker（若未装）
#   ② 拉取 / 更新 GitHub 代码
#   ③ 用 Dockerfile 构建镜像
#   ④ 停掉旧容器、启动新容器（开机自启、崩溃自动重启）
#   ⑤ 把容器 7860 端口映射到服务器 80 端口 → 直接用 http://公网IP 访问
# ============================================================

set -e  # 任何一步出错就立即停止，避免带病继续

# ---------- 可按需修改的变量 ----------
REPO_URL="https://github.com/YKS-1125/bushu.git"
APP_DIR="$HOME/bushu"          # 代码拉到哪
IMAGE_NAME="linxiaohe-ai"      # 镜像名
CONTAINER_NAME="linxiaohe-ai"  # 容器名
HOST_PORT=80                   # 服务器对外端口（80=直接 http://IP 访问，无需带端口号）
CONTAINER_PORT=7860            # 容器内 gunicorn 端口（与 Dockerfile 一致）
# --------------------------------------

echo "=================================================="
echo "  林小禾 AI 网站 一键部署"
echo "=================================================="

# ---------- 0. 检查 API 密钥 ----------
if [ -z "$DEEPSEEK_API_KEY" ]; then
  echo ""
  echo "⚠️  没有检测到 DEEPSEEK_API_KEY 环境变量。"
  read -r -p "请粘贴你的 DeepSeek API 密钥（回车确认）: " DEEPSEEK_API_KEY
  if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "❌ 密钥为空，退出。"
    exit 1
  fi
fi

# ---------- 1. 安装 Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  echo ""
  echo "👉 [1/5] 未检测到 Docker，正在安装（约 1-2 分钟）..."
  # 使用国内镜像源加速（阿里云）
  curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
  systemctl enable docker
  systemctl start docker
  echo "✅ Docker 安装完成"
else
  echo ""
  echo "👉 [1/5] Docker 已安装，跳过"
fi

# ---------- 2. 拉取 / 更新代码 ----------
echo ""
if [ -d "$APP_DIR/.git" ]; then
  echo "👉 [2/5] 检测到已有代码，拉取最新版..."
  git -C "$APP_DIR" fetch --all
  git -C "$APP_DIR" reset --hard origin/main
else
  echo "👉 [2/5] 克隆代码到 $APP_DIR ..."
  git clone "$REPO_URL" "$APP_DIR"
fi
echo "✅ 代码就绪"

# ---------- 3. 构建镜像 ----------
echo ""
echo "👉 [3/5] 构建 Docker 镜像（首次约 3-5 分钟，请耐心等）..."
cd "$APP_DIR"
docker build -t "$IMAGE_NAME" .
echo "✅ 镜像构建完成"

# ---------- 4. 停掉旧容器 ----------
echo ""
echo "👉 [4/5] 清理旧容器（若存在）..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# ---------- 5. 启动新容器 ----------
echo ""
echo "👉 [5/5] 启动新容器..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart always \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -e "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}" \
  -e "PORT=${CONTAINER_PORT}" \
  "$IMAGE_NAME"

echo ""
echo "=================================================="
echo "🎉 部署完成！"
echo ""
PUBLIC_IP=$(curl -fsSL --max-time 5 ifconfig.me 2>/dev/null || echo "你的公网IP")
echo "   访问地址： http://${PUBLIC_IP}"
echo ""
echo "常用命令："
echo "   看运行状态：  docker ps"
echo "   看实时日志：  docker logs -f ${CONTAINER_NAME}"
echo "   重启：        docker restart ${CONTAINER_NAME}"
echo "   更新代码后重新部署：再跑一次 bash deploy.sh"
echo "=================================================="
