export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { question, files } = req.body;

  // 模拟RAG处理（实际部署时替换为真实逻辑）
  const mockAnswer = `根据上传的${files.length}个文档，以下是关于"${question}"的专业回答：

RAG（Retrieval-Augmented Generation）系统在AI产品中的核心价值在于将外部知识库与生成模型结合。针对您的问题，关键设计要点包括：

1. **文档解析质量**：使用Unstructured库确保PDF/Word文档的结构化提取
2. **分块策略**：按语义边界分块（而非固定字符数），保留上下文连贯性
3. **Embedding选型**：text-embedding-3-small在精度与成本间取得平衡
4. **检索优化**：采用HyDE（Hypothetical Document Embeddings）提升召回率

建议参考《AI Engineering Best Practices》第3章的验收标准模板。`;

  const sources = files.map(file => `${file} - 第2.3节 RAG架构设计`);

  res.status(200).json({ 
    answer: mockAnswer, 
    sources: sources 
  });
}
