# RAG Evaluation Results

- Goldset: 78 items · retrieval mode: lexical-only
- Block-anchored subset: 26 items
- Generation eval: 24 cases (20 known + 4 no-answer) · generator: deepseek-v4-flash · judge: deepseek-flash

## Full goldset

| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |
|---|---|---|---|---|---|---|
| naive | 78 | 61.5% | 82.0% | 0.696 | 0.435 | 9.97 |
| hybrid | 78 | 70.5% | 85.9% | 0.768 | 0.433 | 25.45 |
| hybrid_parent_child | 78 | 73.1% | 83.3% | 0.775 | 0.394 | 31.89 |

## Block-anchored subset (strategy differences only show here)

| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |
|---|---|---|---|---|---|
| naive | 26 | 65.4% | 84.6% | 0.734 | 10.11 |
| hybrid | 26 | 69.2% | 88.5% | 0.769 | 25.34 |
| hybrid_parent_child | 26 | 73.1% | 88.5% | 0.798 | 32.43 |

## Generation eval (hybrid_parent_child)

| metric | value |
|---|---:|
| answer correctness | 97.9% |
| faithfulness | 84.5% |
| answer relevance | 100.0% |
| citation presence | 100.0% |
| citation accuracy | 92.7% |
| citation coverage | 95.0% |
| refusal recall | 100.0% |
| false refusal rate | 5.0% |
| avg TTFT | 1671.0 ms |
| avg end-to-end | 3154.5 ms |

### Failure cases

| case | issues | answer excerpt |
|---|---|---|
| eval-metric-families | false_refusal, invalid_citation | **结论：参考资料中没有给出“RAG 系统的核心评估指标分为哪两大类”这一分类，因此无法据其作答。**  参考资料中与评估相关的条目，仅有 [1] 在“评估指标”下列出的通用客服指标：`准确率`、`拦截率`、`CSAT（Customer Satisfaction）`、`FCR（First Contact Resolution）`。这些指标面向 AI 客服的整 |
| prd-hybrid-retrieval | invalid_citation, low_faithfulness | **混合检索的两路召回分别是向量检索与倒排索引（BM25 关键词匹配）**[1]。  具体分工如下：  - **向量检索（Dense Retrieval）**：使用 `OpenAI text-embedding-3-small` 进行向量表征，负责语义层面的召回[1]。 - **倒排索引检索（Sparse Retrieval）**：使用 `BM25` 做关键 |
| evolution-agent-modules | low_faithfulness | **客服4.0的AI Agent由五个核心能力模块组成**：感知模块、推理模块、记忆模块、工具模块和行动模块 [4]。  各模块职责如下：  - **感知模块**：支持多模态输入，包括语音识别、图像识别与文本理解，用户可通过文字、语音甚至上传图片与Agent交互 [4]。 - **推理模块**：基于`Chain-of-Thought`（思维链）进行复杂推理， |
| platform-kb-role | invalid_citation, low_faithfulness | **知识库模块是智能客服平台的"大脑记忆库"**，用于存储所有可复用的服务信息（如产品信息、政策规则、解决方案），为 AI 与人工客服提供统一的答案支撑[2]。  **支持存储的内容类型**  - **结构化内容**：`FAQ`（常见问题，如"退款时效是多久"）与结构化数据（如产品参数、价格表）[2]。 - **非结构化内容**：用户手册、政策文档、历史案例 |
| electronics-three-risks | low_faithfulness | 文章指出，电子产品电商市场背后暗藏三大核心风险：  **1. 售后服务不力**——直接影响用户体验和复购率，售后流程繁琐、响应慢会引发投诉、退单乃至恶意差评，用户流失率剧增 [1]。  **2. 质保体系不完善**——带来用户维权难和信任危机，质保政策模糊、流程复杂会推高投诉量与退换货率，平台还可能面临监管处罚 [1]。  **3. 翻新产品混淆市场**—— |
