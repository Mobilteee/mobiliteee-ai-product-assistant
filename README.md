# AI 产品知识助手 · AI Product Knowledge Assistant

面向 **AI 产品岗求职与日常工作** 的 RAG 知识问答工作台：上传 PRD / 竞品报告 / 面试资料，即可对多文档做
**带引用的流式问答**。产品面 = **Next.js 前端 + FastAPI 后端（SSE 流式）**，内部调试/评测台保留 Streamlit；
检索经过 **父子分块 + BM25/向量混合 + 块级评测** 打磨，并提供 **BYOK + Demo 频次保护**，适合直接部署公网 Demo。

> 状态对照：`UPGRADE_PLAN.md` 的 P0–P3 已完成，P4 容器化/部署配置已就绪（见「部署」）。

---

## ✨ 功能亮点

- **流式问答 + 引用溯源**：`event: sources → token* → done` SSE 协议，答案旁可定位原文切片。
- **三档检索策略**：`naive` / `hybrid`(BM25+向量+RRF) / `hybrid_parent_child`（默认，子块召回+父块全文注入），
  融合分低于阈值时**拒答**而非硬编，天然带幻觉护栏。
- **跨语言 RAG**：多语言 Embedding 可直接召回中文切片；英文弱命中时按需轻量改写再检索，生成语言跟随提问语言。
- **主题分类 · 作用域隔离**：`documents.category` 元数据（智能客服 / 电商售后 / 架构权限 / 产品综合…）；
  前端分类 Chip → 后端**打分前 Metadata 硬过滤**，避免跨领域误召回。`GET /documents/categories` 返回分类树。
- **评测闭环**：78 条手写检索金标（块级 hit@1 / hit@4 / MRR）＋ 20 条生成金标与 4 条无答案拒答题；
  评测 answer correctness、faithfulness、引用准确率和拒答召回率，`/dashboard` 直出对比表。
- **BYOK + Demo 配额**：访客免 Key 用部署者 Demo Key 体验（全局每分钟 + 单 IP 每小时限流，预设推荐问题走
  **静态答案缓存、不耗 Token**）；填入自己的 Key（`X-Custom-Api-Key`）即绕过限流、解锁无限调用。

---

## 🏗 架构

```
┌──────────────────────────────┐        ┌─────────────────────────────────────┐
│ Next.js (Vercel)             │ HTTPS   │ FastAPI (Railway/Render/Docker)     │
│  /        主问答工作台         │  +SSE   │  /query  SSE · /documents* · /feedback │
│  /dashboard  评测看板         │────────▶│  /metrics · /retrieval/config · /health │
│  /pancake  演示风格页          │        ├─────────────────────────────────────┤
│  BYOK Key 存浏览器 LocalStorage│        │  core/ rag · storage · providers · exporters │
└──────────────────────────────┘        ├─────────────────────────────────────┤
                                        │  SQLite (data/app.db) ← 默认         │
                                        │  Postgres/pgvector ← 适配路线图        │
                                        │  producttext/*.md ← demo 语料 seed   │
                                        └─────────────────────────────────────┘

Streamlit (app.py) ── 内部调试/评测工作台（多用户账号 demo / demo1234）
```

**设计取舍**（详见 `docs/EVAL_REPORT.md` 与 `UPGRADE_PLAN.md`）：语料是需求/竞品文档、实体关系稀疏，
**明确不做 Graph RAG**；后端需要 SSE 长连接，**不上 Serverless**；Streamlit 保留为内部台而非对外产品面。

---

## 🚀 本地快速开始

```bash
# 1) 后端
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # 填 DEMO_CHAT_API_KEY 等（见 .env.example 注释）
python -m uvicorn backend.main:app --reload --port 8000
# 启动时自动把 producttext/ 语料 seed 进 data/app.db；GET /health 返回 {"status":"ok"}

# 2) 前端
cd frontend
npm install
npm run dev                        # http://localhost:3000 （CORS 默认放行该源）
```

打开 `http://localhost:3000`：左侧可上传 `.md/.pdf/.docx`、勾选文档或**业务分类**，中间提问，右侧看引用。

> 没配 `DEMO_CHAT_*` 前 Demo 通道不可用——请填真实可用的模型名（示例 DeepSeek 网关当前接受 `deepseek-v4-flash`，
> **不接受** `deepseek-chat`）。可选配 `DEMO_EMBED_*`；不配则自动降级为词法 BM25，保证只有聊天 Key 也能用。

---

## 🔑 自定义 Key（BYOK）与 Demo 配额

- 前端右上角 **个人设置** 可填 API Key / Base URL / 模型，仅存浏览器 LocalStorage；请求以
  `X-Custom-Api-Key` Header 透传。有自定义 Key → 后端优先用该 Key 调用且**绕过 Demo 限流**。
- 未填 Key 的访客 → 走系统 Demo Key，受保护：
  - 全局：所有访客共享 **每分钟真实调用 ≤ `RATE_LIMIT_GLOBAL_PER_MIN`**（默认 8）
  - 单 IP：**每小时自定义提问 ≤ `RATE_LIMIT_IP_PER_HOUR`**（默认 8，推荐问题豁免）
  - 超限返回 `429` + 友好提示；生成侧单次强制 `max_tokens=800`。
- 6 个**推荐问题**（首页预设卡）命中内置**静态答案缓存**：秒回、不耗 Token、不计配额（`backend/main.py` 的
  `PRESET_STATIC_RESPONSES`，想改文案直接编辑该处）。

---

## 🧪 RAG 评测

```bash
# 1) 可离线复现的 lexical-only 检索基线
.venv\Scripts\python.exe evals/run_eval.py

# 2) 生成侧评测（自动读取 .env；网关有便宜 judge 时建议显式指定）
.venv\Scripts\python.exe evals/run_eval.py --judge --judge-model deepseek-flash
```

- 检索金标：`evals/goldset.json`（78 条，含 26 条块级锚点子集），指标为 hit@1 / hit@4 / MRR。
- 生成金标：`evals/generation_cases.json`（20 条有答案 + 4 条无答案），指标为 answer correctness、faithfulness、
  answer relevance、citation accuracy/coverage、refusal recall、TTFT。
- 结果写入 `evals/EVAL_RESULTS.*`，由 `/dashboard` 读取；完整方法论与解读见 **`docs/EVAL_REPORT.md`**。

---

## 🐳 部署

### 后端（Docker / Railway / Render 等长驻进程）
```bash
docker build -t ai-rag-backend .
docker run --rm -p 8000:8000 \
  -v ai-rag-data:/app/data \
  --env-file .env \
  ai-rag-backend
# 健康检查：curl http://localhost:8000/health  ->  {"status":"ok"}
```
- 环境变量以 `.env.example` 为准（含 `CORS_ORIGINS` 白名单、`DATA_DIR`、限流、模型参数）。
- **不要用 Vercel Serverless 跑后端**（SSE 长连接会被截断）；前端部署 Vercel 时把 `NEXT_PUBLIC_API_BASE`
  指向后端域名。

### 数据库
默认本地 SQLite（`DATA_DIR`，Docker 挂卷持久化）。接入 Supabase/PostgreSQL + pgvector 的连接说明与适配路线图见
**`docs/SUPABASE_DEPLOY.md`**（含 embedding 维度、Repository 双实现、检索过滤下推等）。

---

## 📁 目录结构

```text
.
├── backend/main.py            # FastAPI：/query(SSE) /documents* /feedback /metrics /health
├── core/
│   ├── rag.py                 # 解析/父子分块/检索(BM25+向量+RRF)/生成/跨语言/作用域过滤/拒答
│   ├── storage.py             # SQLite：users/documents/categories/chunks/conversations/feedback/query_metrics
│   ├── providers.py           # 模型服务商预设
│   └── exporters.py           # Markdown/PDF 导出
├── frontend/                  # Next.js：/(page.js) /pancake /dashboard；src/lib/api.js、i18n.js
├── producttext/               # demo 语料（seed 用，含分类映射）
├── evals/                     # goldset · generation_cases · run_eval · EVAL_RESULTS.*
├── scripts/                   # migrate_kb.py · assign_categories.py
├── tests/                     # scope filter + evaluator metric regressions
├── docs/                      # PRD.md · EVAL_REPORT.md · SUPABASE_DEPLOY.md
├── app.py                     # Streamlit 内部调试/评测台（demo / demo1234）
├── Dockerfile · .dockerignore
├── .env.example
└── UPGRADE_PLAN.md            # 迭代规划（含取舍叙事）
```

---

## ⚠️ 安全与合规

- **访客 API Key 永不落库**：仅存在于单次请求 / 浏览器 LocalStorage；服务端只持有你自己的 `DEMO_CHAT_*` 密钥。
- `.env`、`data/`、`.venv`、`node_modules` 均已 gitignore；`producttext/` 内若收录第三方文章请自行确认版权后使用。
- Demo 限流为进程内存窗口，多实例部署请换共享存储（见 `docs/SUPABASE_DEPLOY.md` 红线说明）。
