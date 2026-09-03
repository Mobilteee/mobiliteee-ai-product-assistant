# AI 产品经理高频面试题与知识沉淀手册

## 1. RAG 系统的核心评估指标有哪些？
* **检索质量 (Retrieval Metrics)**：
  * Hit Rate@K（前 K 个结果是否包含真实答案）
  * MRR (Mean Reciprocal Rank，真实答案在检索结果中的平均倒排位置)
  * Precision & Recall
* **生成质量 (Generation Metrics - Ragas 框架)**：
  * Faithfulness（忠实度：回答是否完全基于检索上下文，有无幻觉）
  * Answer Relevance（答案相关度：回答是否切中用户问题）
  * Context Precision & Recall（上下文精度与召回度）

## 2. 为什么实际生产中需要加 Reranker（重排序）？
* 纯向量检索（Dense Retrieval）依赖余弦相似度，容易受到语义泛化影响，把相关但不核心的切块排在前面。
* BM25 擅长精准关键词但缺乏语义泛化。
* 重排模型（Cross-Encoder 架构）能够同时计算 Query 与 Document 的完整交叉注意力，排序精度极高，但计算开销大；因此采用“粗排召回多条 + 精排筛选 Top-K”的折中方案。

## 3. 面试表达框架：如何向业务方解释 RAG 系统的价值？
* **降成本**：无需对大模型进行高昂且容易过时的微调（Fine-Tuning），直接外挂企业动态知识库。
* **可追溯**：每个生成的观点都可以溯源到特定文档的切片（Citation），方便人工核验与风控审计。
* **数据安全**：结合企业内部权限体系，可在检索阶段做文档级/部门级隔离，杜绝越权访问。