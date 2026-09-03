# AI 产品知识助手 V2.0（多用户 BYOK 版）PRD

## 1. 背景与问题

### 1.1 背景
面向 AI 产品岗求职者，市面上缺少一个同时具备「专业知识库问答 + 多用户学习记录 + BYOK 隐私 + 结构化诊断」的轻量工具。现有通用 AI 工具没有产品岗语境，也不方便沉淀个人使用轨迹。

### 1.2 目标
构建一个可部署的多用户 RAG 应用，让每位用户：
- 用自己的 OpenAI API Key（BYOK）完成真实问答，不共享他人额度
- 上传 PRD / 竞品分析 / 行业报告，建立个人知识库
- 保留每个会话与使用记录，方便复盘与面试展示
- 一键获得 PRD 诊断建议，并导出 Markdown / PDF

## 2. 用户画像

| 画像 | 场景 | 关键诉求 |
|------|------|----------|
| AI 产品岗求职者 | 准备面试、补 PRD 写作知识 | 专业问答、记录沉淀 |
| 初级产品经理 | 写 PRD、评审竞品 | 快速诊断、结构化输出 |
| 面试官 / HR | 验证候选人真实作品 | 可在线体验、有产品思维证据 |

## 3. 功能需求

| 模块 | 功能 | 优先级 | 说明 |
|------|------|--------|------|
| 账号 | 注册 / 登录 / 退出 | P0 | SQLite + PBKDF2 密码哈希 |
| BYOK | 会话内输入用户自己的 Key | P0 | Key 不落库，刷新即失效 |
| 知识库 | 上传 PDF / DOCX / MD / TXT | P0 | pypdf / python-docx / 文本解析 |
| 知识库 | 自动分块 + Embedding 索引 | P0 | OpenAI Embedding + JSON 存储 |
| 问答 | 基于知识库的引用式回答 | P0 | 余弦相似度检索 top4 |
| 会话 | 新建 / 选择 / 重命名 / 删除 | P1 | SQLite 持久化 |
| 诊断 | 一键生成 PRD 诊断建议 | P1 | 结构化报告 |
| 导出 | 会话与报告导出 MD/PDF | P1 | reportlab 中文 PDF |

## 4. 数据模型

- users：id / username / password_hash
- conversations：id / user_id / title / created_at
- messages：id / conversation_id / role / content / sources / created_at
- kb.json（每用户）：{ chunks: [{ source, text, embedding }] }

## 5. 非功能需求

- 隐私：服务端不保存任何 OpenAI API Key
- 隔离：知识库与会话均按 user_id 隔离
- 轻量：依赖仅 Streamlit / openai / pypdf / python-docx / reportlab
- 可扩展：预留迁移 Supabase + PostgreSQL(pgvector) 的接口

## 6. 验收标准

- [x] 新用户可注册并登录，演示账号 `demo / demo1234`
- [x] 每用户可独立上传并检索自己的文档
- [x] 问答回答带引用来源（来源编号 + 相关度）
- [x] 会话历史按用户持久化，可重命名和删除
- [x] 一键生成 PRD 诊断报告
- [x] 会话与报告可导出 Markdown 与 PDF

## 7. 路线图

- V2.1：流式输出、会话侧边栏体验优化
- V3.0：Supabase Auth + Postgres(pgvector)，生产级多租户持久化
- V3.1：混合检索（BM25 + 语义）、Langfuse 观测埋点
