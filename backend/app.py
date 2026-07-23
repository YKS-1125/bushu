# ============================================================
#  第 ③b 步：用 Flask 把 AI 对话包装成"网页后端 API"
#
#  核心思路：
#    之前 AI 只能在命令行聊。现在我们开一个"小服务器"，
#    它一直在后台监听。网页把用户的话用 HTTP 请求发过来，
#    这个服务器转发给 DeepSeek，再把回答用 HTTP 传回网页。
#
#    浏览器(前端)  ──HTTP请求 /chat──▶  Flask(本文件)  ──▶  DeepSeek
#    浏览器(前端)  ◀──JSON回答─────────  Flask(本文件)  ◀──  DeepSeek
#
#  图例：🟢可变 = 可自由修改   🔴固定 = 语法/结构，别动
# ============================================================

import os                              # 🔴固定
import time                            # 🔴固定：限流要用"当前时间"算时间窗口
import json                            # 🔴固定：把"引用来源"（编号+原文片段）打包成 JSON 发给前端
import pickle                          # 🔴固定：读取第2步保存的"向量化器"tfidf.pkl
import chromadb                        # 🔴固定：连接第2步建好的向量数据库
from collections import defaultdict    # 🔴固定：限流用的"带默认值的字典"
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory   # 🔴固定：Flask 核心工具（新增 Response / stream_with_context 用于流式；send_from_directory 用于托管前端页面）
from flask_cors import CORS            # 🔴固定：解决"跨域"问题（下面术语备注有解释）
from openai import OpenAI              # 🔴固定
from dotenv import load_dotenv         # 🔴固定

# 读取 .env 里的 key（和命令行版一样）
load_dotenv()                          # 🔴固定

# ------------------------------------------------------------
# 1. 建立连大模型的客户端（和之前完全一样）
# ------------------------------------------------------------
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),   # 🟢可变：环境变量名
    base_url="https://api.deepseek.com",          # 🟢可变：服务商地址
)

# 人设：整个网站助手的性格由这里决定（🟢可变）
SYSTEM_PROMPT = "你是林小禾的个人网站助手，友好、简洁地回答访客的问题。林小禾是一名前端 & Python 工程师，擅长 AI Agent、RAG、Prompt 工程。"

# ------------------------------------------------------------
# 1.5 【RAG 基础设施】加载第2步的成果：向量化器 + 向量数据库
#     ——这两行只在服务器启动时执行一次，之后每次提问都复用，省时间
# ------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))       # 🔴固定：本文件所在目录

# (a) 读回第2步用 pickle 存的 TF-IDF 向量化器（必须和建库时是同一个，否则向量对不上）
with open(os.path.join(HERE, "tfidf.pkl"), "rb") as f:   # 🔴固定
    vectorizer = pickle.load(f)

# (b) 连接第2步建好的向量库，拿到那张名叫 linxiaohe 的表
chroma_client = chromadb.PersistentClient(path=os.path.join(HERE, "chroma_db"))  # 🔴固定
collection = chroma_client.get_collection("linxiaohe")                            # 🔴固定：get=取已存在的


# ------------------------------------------------------------
# 1.6 【★练手★】检索函数：给一句问题，返回最相关的 k 段资料
#
#   目标：question(文字) → 向量 → 在 collection 里查最像的 k 段 → 返回文字列表
#   你需要填两行（提示都写在注释里）：
# ------------------------------------------------------------
# 【相关性阈值】余弦距离 ≥ 此值视为"基本无关"，直接丢弃，避免给跑题问题硬塞资料。
#   经真实校准（见 _calib）：完全无关的问题（如"美国总统是谁""写首诗"）对所有知识块
#   距离≈1.000（零字符重叠）；相关问题 top 命中普遍在 0.88~0.96。故默认 0.97 只滤除
#   "零重叠"噪声，不误伤相关问题。⚠️TF-IDF 无法区分"天气→FAQ"这类功能词噪声，
#   更精细的语义区分需升级为神经 embedding（见开发规划③）。
RAG_MAX_DISTANCE = float(os.environ.get("RAG_MAX_DISTANCE", "0.97"))   # 🟢可变：env 可调

def search_knowledge(question, k=4, max_distance=RAG_MAX_DISTANCE):    # 🟢可变：k=返回几段；max_distance=相关性阈值
    # ① 把“问题文字”变成向量（用同一个 vectorizer，与建库时完全一致）
    #   • [question] 🔴固定要加方括号：transform 接收的是“一批文本”，哪怕只查一句也得装成列表
    #   • .toarray() 🔴把稀疏矩阵转成普通数组；.tolist() 🔴转成 Python 列表，chromadb 才认
    q_vec = vectorizer.transform([question]).toarray().tolist()   # 🔴固定写法

    # ② 拿向量去向量库查最相似的 k 段（同时取回 distances 用于相关性过滤）
    #   • query_embeddings 🔴传向量（不是文字）；n_results=k 🟢控制返回几段
    res = collection.query(query_embeddings=q_vec, n_results=k)   # 🔴固定写法
    docs = res["documents"][0]                       # 🔴docs[0] 才是那批文字
    dists = (res.get("distances") or [[None] * len(docs)])[0]   # 🔴每段的余弦距离（越小越相关）

    # ③ 【相关性过滤】距离过大的直接丢弃；过滤后按顺序重新编号，
    #    保证发给 AI 的 [1][2] 与返回给前端的引用一一对应
    hits = []                                        # 🟢存 {编号, 给AI看的带号原文, 原文片段, 距离}
    for doc, dist in zip(docs, dists):
        if dist is not None and dist >= max_distance:   # 距离≥阈值=基本无关 → 丢
            continue
        idx = len(hits) + 1                          # 重新编号（1,2,3...）
        hits.append({
            "id": idx,
            "display": f"[{idx}] {doc}",             # 🟢给 AI 看（带编号，引导它引用 [1][2]）
            "snippet": doc,                          # 🟢给前端点击展开时显示的原文
            "distance": dist,
        })
    return hits          # 🔴返回结构化命中列表（可能为空=没检索到相关资料）


# ------------------------------------------------------------
# 2. 创建 Flask 应用，并允许网页跨域访问
# ------------------------------------------------------------
app = Flask(__name__)                  # 🔴固定：创建一个 Web 应用

# 【CORS】默认放行全部（本地开发方便）；生产环境用 ALLOWED_ORIGINS 收紧为白名单
#   例：ALLOWED_ORIGINS="https://linxiaohe.dev,https://www.linxiaohe.dev"
#   前后端同源部署（Flask 自己托管前端）时其实用不到跨域，配了更安全
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _allowed_origins:
    CORS(app, resources={r"/chat": {"origins": _allowed_origins}})   # 只放行白名单域名
else:
    CORS(app)                          # 🟢未配置=放行全部（仅开发用；上线务必设置 ALLOWED_ORIGINS）

# 前端页面目录：兼容两种运行结构
#   · 本地直接跑 backend/app.py：前端在 backend 的同级目录 ../frontend
#   · 容器里整个项目 COPY 到 /app：前端在 /app/frontend（同样是上一级）
# 逐个候选路径找到真正包含 index.html 的那个，找不到就用第一个兑底
_frontend_candidates = [
    os.path.join(os.path.dirname(HERE), "frontend"),   # .../项目根/frontend
    os.path.join(HERE, "frontend"),                     # backend/frontend（兑底）
]
FRONTEND_DIR = next(
    (p for p in _frontend_candidates if os.path.exists(os.path.join(p, "index.html"))),
    _frontend_candidates[0],
)   # 🟢可变：前端 index.html 所在目录

# ------------------------------------------------------------
# 2.1 【托管前端】访问根路径 "/" 时，直接把个人网页发回浏览器
#     这样前后端同源（都在 5000 端口），前端调 "/chat" 免跨域
# ------------------------------------------------------------
@app.route("/")                        # 🟢可变：网址 "/"（网站首页）
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")   # 🔴固定：把 frontend/index.html 作为首页返回

# ------------------------------------------------------------
# 2.5 【限流】防止同一个人短时间狂点——刷爆 API = 烧钱
#     思路：按 IP 记下每次访问的"时间戳"，只看最近 RATE_WINDOW 秒内达到几次
#
#   ⚠️ 局限：这是"内存版"限流，_visits 跟随进程。因此：
#     · 多进程（gunicorn workers>1）时每个进程各自计数，实际阈值会成倍放大
#     · 服务重启/休眠唤醒后计数清零
#   本项目 Render 免费版固定 WEB_CONCURRENCY=1，单进程下足够用；
#   若上多进程/多实例的高流量场景，应改用 Redis 做集中式限流。
# ------------------------------------------------------------
RATE_LIMIT = 10                        # 🟢可变：时间窗口内最多允许几次
RATE_WINDOW = 60                       # 🟢可变：时间窗口长度（秒），这里=每60秒最多10次
_visits = defaultdict(list)            # 🔴固定：{ip: [时间戳, ...]}，记每个 IP 的访问时刻

# 【输入上限】防止超长输入/超长历史拉爆 token（=烧钱）
MAX_MESSAGE_CHARS = 2000               # 🟢单条消息最大字符数
MAX_HISTORY_MESSAGES = 40              # 🟢保留的最近几条历史（超出只取末尾，防上下文膨胀）

def is_rate_limited(ip):               # 返回 True=超限了，该拦；False=放行
    now = time.time()                  # 🔴当前时间（秒）
    # 只保留"还在窗口内"的访问记录，过期的丢掉
    _visits[ip] = [t for t in _visits[ip] if now - t < RATE_WINDOW]   # 🔴固定
    if len(_visits[ip]) >= RATE_LIMIT: # 窗口内次数已满 → 拦
        return True
    _visits[ip].append(now)            # 未满 → 记下这次访问，放行
    return False

# ------------------------------------------------------------
# 3. 定义一个接口 /chat：网页往这里发消息，就返回 AI 回答
#    @app.route 叫"路由"，意思是"访问 /chat 这个网址时，执行下面的函数"
# ------------------------------------------------------------
@app.route("/chat", methods=["POST"])  # 🟢可变：网址 "/chat"；🔴固定：@app.route、methods 写法
def chat():
    # (0) 【限流】先看这个访客(按 IP)是不是发得太频繁
    ip = request.remote_addr           # 🔴固定：访客的 IP 地址
    if is_rate_limited(ip):            # 超过阈值就直接拒绝，不再调用大模型（省钱防刷）
        return Response("你问得太快啦，请过一会儿再试～", mimetype="text/plain", status=429)  # 429=请求过多

    # (1) 从网页发来的请求里取出对话历史
    data = request.get_json(silent=True) or {}   # 🔴固定：silent=True 解析失败不报错(返回 None)，再用 or {} 兑底
    history = data.get("messages", []) # 🟢可变：键名 "messages" 要和前端约定一致

    # (1b) 【输入校验】没有有效内容就别白白浪费一次 API 调用
    if not history:                    # 空列表/没传 messages
        return Response("请先说点什么呀～", mimetype="text/plain", status=400)  # 400=请求不合法

    # (1c) 【输入上限】拦住超长输入 + 裁剪超长历史，防 token 膨胀/烧钱
    last_content = ((history[-1] or {}).get("content") or "") if isinstance(history[-1], dict) else ""
    if len(last_content) > MAX_MESSAGE_CHARS:
        return Response(f"输入太长啦（上限 {MAX_MESSAGE_CHARS} 字），精简一下再发吧～", mimetype="text/plain", status=400)
    if len(history) > MAX_HISTORY_MESSAGES:   # 只保留最近 N 条（过长历史拉高成本）
        history = history[-MAX_HISTORY_MESSAGES:]

    # (2) 【RAG 核心】先拿“最新一句用户提问”去检索知识库
    #     从历史里找最后一条 role==user 的内容作为查询词
    last_question = ""
    for msg in reversed(history):                    # 🔴从后往前找
        if msg.get("role") == "user":
            last_question = msg.get("content", "")
            break

    hits = []                                          # 🟢新：结构化命中列表
    if last_question:
        hits = search_knowledge(last_question)         # 🔴已含相关性过滤，可能为空

    # ① 拼纯文本的知识内容（给 AI 看，让它引用 [1][2]）
    knowledge_text = "\n\n".join(h["display"] for h in hits)   # 🔴拼接成一大段

    # ② 【引用 payload】带上原文片段（截断到 120 字），供前端点击展开
    cited_payload = [
        {"id": h["id"], "text": h["snippet"][:120] + ("…" if len(h["snippet"]) > 120 else "")}
        for h in hits
    ]

    # (3) 【注入 Prompt】把检索到的资料塞进 system 人设；若零命中则明确告知没资料
    if knowledge_text:
        system_content = (
            SYSTEM_PROMPT
            + "\n\n以下是你掌握的【林小禾相关资料】，回答时优先依据它们，若资料里没有就如实告知：\n"
            + knowledge_text
        )   # 🟢可变：这段提示词可以改措辞
    else:
        # 没检索到相关资料（问题与林小禾无关，或距离都超阈值）：不硬塞资料，避免编造
        system_content = (
            SYSTEM_PROMPT
            + "\n\n（本次没有检索到与问题相关的林小禾资料。若问题与林小禾无关，请友好简洁地回应；"
            + "若涉及林小禾的具体事实而你不确定，请如实说明不了解，不要编造。）"
        )

    # (4) 把 system 人设（已注入资料）放最前面，拼上前端传来的对话历史
    messages = [{"role": "system", "content": system_content}] + history


    # (5) ★流式核心★：定义一个"生成器"，边收 DeepSeek 的碎片边往外 yield
    #     生成器 = 用 yield 的函数，能"产出一个、暂停、再产出下一个"
    def generate():
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",     # 🟢可变
                messages=messages,         # 🔴关键：发整段历史
                stream=True,               # ★🔴开启流式（和你第1关一模一样）
            )
            # 下面这段循环，和你命令行第1关写的几乎一模一样！
            for chunk in stream:
                delta = chunk.choices[0].delta.content   # 🔴这一小块新增文字
                if delta:                                # 🔴过滤空块
                    yield delta                          # 🔴把碎片立即"吐"给浏览器（不是 print，是 yield）
        except Exception as e:
            # 大模型调用失败（密钥错/余额不足/网络断）不让服务器崩，友好告知
            print("调用大模型出错：", e)   # 🔴打到后端控制台，方便你排查真正原因
            yield "\n[抱歉，AI 暂时无法回答，请稍后再试]"   # 🟢可改提示语
        finally:
            # ★引用来源：流式结束后发送 JSON（编号+原文片段），前端据此做可点击展开的引用
            if cited_payload:
                yield "\n__REF__:" + json.dumps(cited_payload, ensure_ascii=False)


    # (6) 用 Response 包住生成器 = 流式响应
    #     stream_with_context 🔴固定：让流式期间还能访问请求信息
    #     mimetype="text/plain" 🟢可变：告诉浏览器这是纯文本流
    return Response(stream_with_context(generate()), mimetype="text/plain")

# ------------------------------------------------------------
# 4. 启动服务器（跑在本机 5000 端口）
# ------------------------------------------------------------
if __name__ == "__main__":             # 🔴固定：Python 的"程序入口"写法
    # debug=True：改代码自动重启，报错显示详情，方便开发
    # 部署时不要 set True，避免泄露细节
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))     # 🟢可变：允许外部访问
