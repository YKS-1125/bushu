# ============================================================
# build_index.py —— RAG 第2步：把知识库【切块 → 向量化 → 存进向量数据库】
# 用法：知识库内容变了就运行一次它，重建索引
#   python build_index.py
#
# 说明：向量化(embedding)本可用神经网络模型，但那个模型要联网下载(很慢)。
#       这里改用轻量的 TF-IDF(字符级) 自己算向量——同样能存进向量库、能检索，
#       零大文件下载。等网络方便时可无缝换成神经 embedding。
# ============================================================

import os                                  # 🔴固定：处理文件路径
import pickle                              # 🔴固定：把"向量化器"存到硬盘，供 app.py 复用
import chromadb                            # 🔴固定：向量数据库
from sklearn.feature_extraction.text import TfidfVectorizer   # 🔴固定：TF-IDF 向量化工具

HERE = os.path.dirname(os.path.abspath(__file__))       # 🔴固定：本脚本所在目录

# ------------------------------------------------------------
# 1. 读取知识库文件
# ------------------------------------------------------------
KB_PATH = os.path.join(HERE, "knowledge", "林小禾.md")   # 🟢可变：知识库文件路径
with open(KB_PATH, encoding="utf-8") as f:   # 🔴固定：encoding 必须 utf-8，否则中文乱码
    text = f.read()

# ------------------------------------------------------------
# 2. 切块（Chunking）：按 Markdown 的 "## " 小节切开
#    原理：每个小节讲一个独立话题 → 切成一块 → 检索才精准
# ------------------------------------------------------------
raw_parts = text.split("\n## ")          # 🟢可变：用 "## " 当分隔符
chunks = []                              # 🟢可变：存所有知识块
for part in raw_parts:
    part = part.strip()
    if not part or part.startswith("# "):  # 🔴跳过空块 & 最前面的大标题+说明段
        continue
    chunks.append(part)
print(f"✅ 切出 {len(chunks)} 个知识块")

# ------------------------------------------------------------
# 3. 向量化（Embedding）：把每块文字变成一串数字（向量）
#    analyzer='char_wb' + ngram(2,3)：按 2~3 个字的片段统计 → 适合中文
# ------------------------------------------------------------
vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))  # 🟢可变：中文用字符 n-gram
doc_vectors = vectorizer.fit_transform(chunks).toarray()             # 🔴学习词表 + 把每块转成向量
print(f"✅ 每块向量维度 = {doc_vectors.shape[1]}")

# 把训练好的"向量化器"存硬盘 —— app.py 要用同一个才能把"问题"转到同一空间
with open(os.path.join(HERE, "tfidf.pkl"), "wb") as f:   # 🔴固定：pickle 保存
    pickle.dump(vectorizer, f)

# ------------------------------------------------------------
# 4. 连接向量数据库，建"集合"（collection，相当于一张表）
#    metadata hnsw:space=cosine：用"余弦相似度"比较向量（TF-IDF 的最佳搭配）
# ------------------------------------------------------------
client = chromadb.PersistentClient(path=os.path.join(HERE, "chroma_db"))  # 🔴固定：持久化到本地
try:
    client.delete_collection("linxiaohe")   # 每次重建先删旧的，避免重复
except Exception:
    pass
collection = client.create_collection("linxiaohe", metadata={"hnsw:space": "cosine"})  # 🟢可变：集合名

# ------------------------------------------------------------
# 5. 入库：把【自己算好的向量】+ 原文 + 唯一 id 一起加进去
#    ★ 传了 embeddings，chromadb 就不会去下载那个模型自己算了 ★
# ------------------------------------------------------------
collection.add(
    embeddings=doc_vectors.tolist(),                    # 🔴我们自己算的向量
    documents=chunks,                                   # 🔴每块原文
    ids=[f"chunk-{i}" for i in range(len(chunks))],     # 🔴每块唯一编号
)
print(f"✅ 已入库 {collection.count()} 条，向量库位于 ./chroma_db")

# ------------------------------------------------------------
# 6. 自测：查一句，看能不能检索到最相关的块
# ------------------------------------------------------------
q = "林小禾在哪个城市？"                                   # 🟢可变：测试问题
q_vec = vectorizer.transform([q]).toarray().tolist()     # 🔴用同一个向量化器把问题转成向量
res = collection.query(query_embeddings=q_vec, n_results=2)
print(f"\n🔍 检索测试 —— 问：『{q}』，命中：")
for doc in res["documents"][0]:
    print("  ↳", doc[:40].replace("\n", " "), "…")
