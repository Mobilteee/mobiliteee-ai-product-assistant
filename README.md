# AI 产品知识助手（多用户版）

面向 AI 产品岗求职与日常工作的 **Streamlit RAG SaaS 雏形**：多用户账号、BYOK（自带 Key）、每人独立知识库与历史记录、PRD 诊断建议、Markdown / PDF 导出。

## 核心亮点

- 多用户注册 / 登录，数据按用户隔离
- BYOK：每位用户填写自己的 OpenAI API Key，仅在浏览器会话内使用，不写入数据库
- 轻量 RAG：无需 LangChain / Chroma，直接用 OpenAI Embedding + 余弦相似度检索
- 上传 PDF / DOCX / Markdown / TXT，自动分块建立索引
- 引用来源展示，避免幻觉
- 一键生成「PRD 诊断与改进建议」
- 导出当前会话与诊断报告（Markdown / PDF）

## 演示账号

- 用户名：`demo`
- 密码：`demo1234`

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## 项目结构

```text
.
├── app.py                 # Streamlit 主界面
├── core/
│   ├── storage.py         # SQLite：用户 / 会话 / 消息
│   ├── rag.py             # 解析、分块、Embedding、检索、生成、建议
│   └── exporters.py       # Markdown / PDF 导出
├── requirements.txt
└── data/                  # 运行时自动创建（已 gitignore）
```

## 部署（Streamlit Community Cloud）

1. 推送仓库到 GitHub
2. 打开 share.streamlit.io → New app → 选择仓库与 `app.py`
3. 无需配置密钥（用户自带 Key）
4. 部署完成后即可访问并注册使用

## 产品思维说明（面试可用）

- 明确用户场景：产品实习面试准备、PRD 写作辅助、竞品分析
- 数据隔离策略：user_id 隔离知识库与会话
- 隐私策略：BYOK 模式，服务端零 Key 存储
- 指标设想：回答引用覆盖率、建议采纳率、会话留存

> 说明：本地 SQLite 适合演示与 MVP；如需生产级多租户持久化，可平滑迁移到 Supabase / PostgreSQL。
