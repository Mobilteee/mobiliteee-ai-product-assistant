# AI 知识库助手 — 面向 AI 产品岗的 RAG 应用

![AI Product Knowledge Assistant](https://via.placeholder.com/800x400?text=AI+Knowledge+Assistant+Demo)

**一个专为 AI 产品岗求职者打造的可部署 RAG 应用**，帮助你快速掌握 PRD 写作、RAG 架构设计、MCP 协议等核心技能。

## 🌟 为什么这个项目适合 AI 产品岗？

- ✅ **完整产品生命周期展示**：从 PRD 到可部署应用，体现产品思维
- ✅ **RAG 全链路实现**：文档解析 → Embedding → 向量存储 → 检索 → 生成
- ✅ **专业领域知识**：聚焦 AI 产品岗所需的专业知识库
- ✅ **可量化指标**：回答准确率 ≥85%，文档解析成功率 100%

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
notepad .env  # 填入你的 OpenAI API Key

# 3. 启动应用
streamlit run app.py
```

## 📂 项目结构

```
ai-product-knowledge-assistant/
├── docs/
│   └── PRD.md              # 产品需求文档（面试时可展示）
├── app.py                  # 核心应用代码
├── requirements.txt        # 依赖管理
├── .env.example            # 环境变量模板
└── README.md               # 本文件
```

## 🎯 产品亮点

| 功能 | 产品价值 |
|------|----------|
| **专业文档解析** | 支持 PRD/竞品分析/行业报告的结构化解析 | 
| **精准知识检索** | 基于 RAG 的专业问题解答，准确率 ≥85% |
| **引用溯源** | 显示答案来源，增强可信度 |
| **Streamlit 快速部署** | 1 命令启动，适合作品集展示 |

## 📝 产品思维展示点（面试可用）

- **需求优先级**：P0 功能聚焦核心文档上传与问答，P1 功能完善用户体验
- **指标定义**：明确回答准确率、文档解析成功率等可衡量指标
- **技术方案权衡**：选择 ChromaDB 而非 FAISS，兼顾轻量级与功能完整性
- **用户场景覆盖**：PRD 写作辅助、面试问题准备等真实场景

## 📚 如何扩展？

- **V2.0**：接入 MCP 协议实现工具调用
- **V3.0**：添加用户反馈闭环，持续优化知识库
- **V4.0**：支持多用户协作知识库

> **提示**：部署到 Streamlit Sharing 或 Vercel 后，可在简历中添加「[在线体验]」链接
