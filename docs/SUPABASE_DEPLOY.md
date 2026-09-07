# Supabase / PostgreSQL 部署连接说明

> 目标：让「AI 产品知识助手」后端能在公网用上托管数据库。
> **当前状态**：存储层为**本地 SQLite**（`data/app.db`），已可经 Docker volume 持久化；Postgres/pgvector 为
> **适配路线图**。本文给出连接契约与落地清单，避免“看似支持 Postgres、实则没接”的坑。

---

## 1. 现在怎么跑（不依赖 Postgres）

- 本地 / 单容器：保持默认，`.env` 只填 `DATA_DIR`（默认 `/app/data`），SQLite 落在该目录。
- Docker 持久化：挂载 volume 到 `/app/data`，上传/会话在重新部署后保留：

```bash
docker run --rm -p 8000:8000 \
  -v ai-rag-data:/app/data \
  --env-file .env \
  ai-rag-backend
```

- 健康检查：`GET /health` → `{"status":"ok"}`（容器 HEALTHCHECK 已内置）。

## 2. 环境契约（将来切换 Postgres）

| 变量 | 值示例 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:xxxx@db.<ref>.supabase.co:5432/postgres?sslmode=require` | 切换后由它驱动，不再用 `DATA_DIR` |
| `DATA_DIR` | `/app/data` | Postgres 模式下仅用于运行期种子等临时产物 |

**连接串来源**：Supabase 控制台 → Project Settings → Database → Connection string
（推荐 **Direct connection** `5432`；若有连接池需求用 **Session pooler** `6543`，注意两者 URL 前缀不同
`postgresql://` vs `postgresql://...-pooler.supabase.co:6543`）。务必带 `?sslmode=require`。

## 3. 当前 SQLite 表 → Postgres 目标映射

| SQLite 表 | 作用 | Postgres 建议 |
|---|---|---|
| `documents` | 文档元数据（含 `category`） | 同结构表 |
| `chunks` | 父/子切片文本 | `text` + **`embedding vector(N)`**（pgvector） |
| `conversations` / `messages` | 会话与消息 | 同结构表 |
| `feedback` | 点踩归因 | 同结构表 |
| `query_metrics` | 埋点 | 同结构表 |
| `users` | 账号 | 同结构表 |

**适配要做的事（路线图）**：
1. 把 `core/storage.py` 的 SQLite 实现抽象为 Repository 接口，提供 SQLite / Postgres 双实现（本地开发仍可离线用 SQLite）；
2. Postgres 实现用 `psycopg`（或 SQLAlchemy）+ `pgvector`：`chunks.embedding` 用与模型一致的维度
   （如 `text-embedding-3-small`=1536，`bge-m3`=1024），检索时 `<=>` 余弦相似度 + 需要时倒排；
3. `retrieve()` 的前置过滤（`category`/`doc_ids`）下推为 SQL WHERE，避免全表拉取后内存过滤；
4. 迁移：从 SQLite dump 导入或在 Supabase 建表后重新入库（提供一次性脚本，参考 `scripts/migrate_kb.py` 思路）。

## 4. 部署红线（务必遵守）

- **后端不要放 Serverless（Vercel Functions 等）**：`/query` 是 SSE 长连接流式，Serverless 会超时截断。后端放
  **Railway / Render / Fly.io 等长驻进程**，再通过平台域名作为 `CORS_ORIGINS` 白名单给 Next.js。
- 前端 Next.js 上 Vercel：设置 `NEXT_PUBLIC_API_BASE=https://<backend-domain>`（前端编译期注入）。
- **访客 Key 绝不落库**：自定义 Key 走 `X-Custom-Api-Key` / 请求体，只活在单次请求内；服务端只存你自己的
  `DEMO_CHAT_*` 部署密钥（平台 Secrets）。
- Demo 限流参数已在 `.env.example` 标注（`RATE_LIMIT_GLOBAL_PER_MIN` / `RATE_LIMIT_IP_PER_HOUR`），
  为**进程内存窗口**——多实例部署需换成共享存储（Redis），单实例演示够用。

## 5. 快速核对清单

- [ ] `GET /health` 返回 200 `{"status":"ok"}`
- [ ] `CORS_ORIGINS` 含真实前端域名（不含协议尾斜杠，逗号分隔）
- [ ] `DEMO_CHAT_MODEL` 为当前网关接受的真实模型名
- [ ] Supabase 若启用：已建表 + pgvector 扩展 + 维度与 embedding 模型一致
- [ ] Docker：volume 挂载 `/app/data`（Postgres 切换前）
