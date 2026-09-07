# Render 部署说明（后端）

后端是 **SSE 长连接**服务，必须跑在长驻进程上（Render / Railway / Fly），**不要用 Serverless**。
前端（Next.js）已配好 Netlify：见根目录 `netlify.toml`。

## 方式 A · 用 render.yaml（推荐）

仓库根目录已有 `render.yaml`（Docker web service）。两种触发：

1. Render 控制台 → **New + → Blueprint** → 选择本仓库，自动按 `render.yaml` 建服务；
2. 或贴文件内容到 Blueprint 编辑器。

部署前记得改占位：
- `envVars` 中 `CORS_ORIGINS` 换成真实前端域名（如 Netlify 生成的 `https://xxx.netlify.app`）；
- `DEMO_CHAT_*`：把 `sync: false` 的 key 在 **Dashboard → Environment** 里填值（不要写进 git）；
- `DEMO_CHAT_MODEL` 用网关真实接受的模型名（示例 DeepSeek 网关当前是 `deepseek-v4-flash`）；
- Region / plan 按需。

## 方式 B · 手动创建

Render Dashboard → **New → Web Service** → 连接仓库：
- **Root Directory**：留空（Dockerfile 在根目录）
- **Runtime**：Docker
- **Health Check Path**：`/health`
- **Instance Type**：Free/Starter
- **Disk**：Add Disk → mount `/app/data`（SQLite 持久化）
- **Environment**：按根目录 `.env.example` 填（CORS 白名单、限流、`DATA_DIR=/app/data`、Demo Key）

## 之后

- 验证：打开 `https://<service>.onrender.com/health` → `{"status":"ok"}`。
- 把该后端域名设到前端：Netlify → Site settings → Environment variables → `NEXT_PUBLIC_API_BASE=https://<service>.onrender.com`，重建前端。
- 数据：默认 SQLite 落 `DATA_DIR` 磁盘；接 Supabase/PostgreSQL 见 `docs/SUPABASE_DEPLOY.md`（届时可去掉磁盘挂载）。
