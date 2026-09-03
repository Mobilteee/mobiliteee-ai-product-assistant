# AI 产品知识助手（多用户 · 多服务商版）

面向 AI 产品岗求职与日常工作的 **Streamlit RAG 应用**：多用户账号、BYOK（自带 Key / 中转站）、每人独立知识库与历史记录、PRD 诊断建议、Markdown / PDF 导出。

## 为什么这样设计？

真实用户不一定有 OpenAI 官方账号，可能使用：

- DeepSeek / Kimi / 通义千问 / 智谱等国内模型
- 各类 OpenAI 兼容中转站、One-API / New-API 聚合服务

本项目把「填 Key」升级为「多配置接入」：

- **对话模型**：可选 OpenAI、DeepSeek、Moonshot、DashScope、BigModel、SiliconFlow、自定义中转站，并可手动填写 Base URL + 模型名
- **Embedding**：可配置 OpenAI / SiliconFlow / DashScope Embedding；未配置时自动降级为「关键词检索」，保证只有聊天 Key 也能用
- **演示通道**：部署者可在 Secrets 配置一个演示 Key，访客免填 Key 直接体验

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

## 可选：配置免 Key 演示通道

在 Streamlit **Settings → Secrets** 中填写：

```toml
DEMO_CHAT_API_KEY = "你的聊天 API Key"
DEMO_CHAT_BASE_URL = "https://api.deepseek.com/v1"   # 可替换为 OpenAI / 中转站
DEMO_CHAT_MODEL = "deepseek-chat"

# 可选：Embedding，不配置则自动使用关键词检索
DEMO_EMBED_API_KEY = "你的 Embedding Key"
DEMO_EMBED_BASE_URL = "https://api.siliconflow.cn/v1"
DEMO_EMBED_MODEL = "BAAI/bge-m3"
```

## 项目结构

```text
.
├── app.py                 # Streamlit 主界面
├── core/
│   ├── storage.py         # SQLite：用户 / 会话 / 消息
│   ├── rag.py             # 解析、分块、Embedding、检索、生成、建议
│   ├── providers.py       # 模型服务商预设
│   └── exporters.py       # Markdown / PDF 导出
├── requirements.txt
└── data/                  # 运行时自动创建（已 gitignore）
```

## 部署（Streamlit Community Cloud）

1. 推送仓库到 GitHub
2. 打开 share.streamlit.io → New app → 选择仓库与 `app.py`
3. 可选在 Secrets 中配置演示通道
4. 部署后即可注册使用或使用 `demo / demo1234`
