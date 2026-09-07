# RAG 检索评测报告（EVAL REPORT）

> 生成方式：`evals/run_eval.py`。原始数字源文件 `evals/EVAL_RESULTS.json` / `EVAL_RESULTS.md`
> （看板 `/dashboard` 读取前者）。语料位于 `producttext/`。
> 评测对象：AI 产品知识助手的检索链路。

---

## 1. 目的与结论

评测回答两个问题：

1. 不同检索策略（naive / hybrid / hybrid_parent_child）在同一份金标集上谁更准、快多少；
2. 把“我做了混合检索 / 父子分块”从形容词变成**有数字支撑**的结论，并诚实标注跑分边界。

**当前结论（10 文档语料，78 条手写金标，词法-only）：**

- 词法检索的精度排序为 **parent_child ≥ hybrid > naive**：
  - hit@1：naive 61.5% → hybrid 70.5% → parent_child 73.1%；
  - MRR：naive .696 → hybrid .768 → parent_child .775（在**块级锚点子集**上 pc 达 **.798**，naive .734）；
  - 即在“第一条引用就要命中”的对话体验指标上，父子分块显著领先 naive，BM25 混合次之。
- **局限（必须主动说明）**：本轮为 `lexical-only`（未配 embedding，向量路未参与）；parent_child 的
  子块召回 + 父上下文注入优势在配向量后预期进一步放大。另：当前 BM25 为全内存线性扫描
  （341 块，单次 ~25–32ms），语料再大需倒排索引/预计算。

---

## 2. 方法论

### 2.1 评测对象与策略

| 策略 | 召回对象 | 打分 | 说明 |
|---|---|---|---|
| `naive` | 父块 | 词法覆盖（query token 命中率） | 基准线 |
| `hybrid` | 父块 | BM25（词法）＋ 可选向量，RRF(k=60) 融合 | 混合检索 |
| `hybrid_parent_child` | **子块** | 同上，命中后注入父块全文 | 父子分块（默认产品策略） |

三档由 `core/rag.py` 的 `RETRIEVAL_STRATEGIES` 驱动，同一份 KB 上切换，横向可比。

### 2.2 金标与命中定义

旧版命中判据是“前 4 个结果里只要出现金标**文档**即算命中” —— 在两三篇文档的语料上会饱和（~96%），
无法区分策略。新版改为**块级锚点 + 排名感知**：

1. 每条金标含 问题 `q`、答案所在文档 `doc`、答案要点 `keywords`（全部**手写**，非 LLM 生成）；
2. 在 `doc` 的父块中，找出“关键词覆盖度最高”的父块集合作为该条**锚点（anchor）**；
3. 命中按策略归一化到父块锚点：naive/hybrid 返回父块直接用父块 id；parent_child 返回子块，用
   子块的 `parent_id` 映射回父块 —— 三条链路在同一锚点体系下可比；
4. 指标：**hit@1 / hit@4 / MRR@4**。

**两个视图**（`run_eval.py` 均输出）：

- `metrics`：全量金标；
- `metrics_block`：**锚点是该文档父块真子集的题目**（即文档 ≥2 父块、锚点确实定位到块）。只指向
  单父块小文档的题目被排除，避免它们掩盖策略差异——**策略差异只可能在块级视图里现形**。

> 诚实边界：`score` 不具备跨检索器可比性（BM25 检索器在代码中以词法 overlap 归一上报用于阈值/展示）。
> 因此横向对比主指标取 hit@1 / hit@4 / MRR，不把 avg top score 当可比口径（看板列已相应调整）。

### 2.3 运行模式标注

脚本检测 `DEMO_EMBED_MODEL / DEMO_EMBED_API_KEY`；存在则在入库阶段写真实向量、检索阶段传入，
产物标注 `mode: embedding`；否则 `mode: lexical-only`。

### 2.4 生成侧（可选 `--judge`）

用 chat 模型生成答案并让“评判模型”打分：`faithfulness`（无幻觉/忠实于检索上下文）与
`answer_relevance`（切题），外加 `avg_ttft_ms`。需要 `DEMO_CHAT_*` / `OPENAI_*` 聊天凭据。

---

## 3. 复现命令

```bash
# 词法-only（离线，默认全量金标）
.venv\Scripts\python.exe evals/run_eval.py

# 含向量（配 DEMO_EMBED_MODEL / DEMO_EMBED_API_KEY / DEMO_EMBED_BASE_URL 后）
set DEMO_EMBED_MODEL=BAAI/bge-m3
set DEMO_EMBED_API_KEY=sk-...
set DEMO_EMBED_BASE_URL=https://api.siliconflow.cn/v1
.venv\Scripts\python.exe evals/run_eval.py

# 检索 + 生成侧（再加聊天凭据）
set DEMO_CHAT_API_KEY=sk-...
set DEMO_CHAT_BASE_URL=...
set DEMO_CHAT_MODEL=...
.venv\Scripts\python.exe evals/run_eval.py --judge
```

输出：刷新 `evals/EVAL_RESULTS.json` 与 `evals/EVAL_RESULTS.md`。

---

## 4. 当前快照（2026-09-07 · 10 篇文档语料 · lexical-only）

语料：`producttext/` 10 篇文档 → seed 后 56 父块 / 341 条 chunk（含父子树）。
金标集：78 条手写，其中 26 条为**块级锚点**（真正会拉开三档策略的子集）。
Generation eval：disabled（运行 `--judge` 可开启）。

### 4.1 全量金标（n=78）

| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |
|---|---|---|---|---|---|---|
| naive | 78 | 61.5% | 82.0% | 0.696 | 0.435 | 10.11 |
| hybrid | 78 | 70.5% | 85.9% | 0.768 | 0.433 | 25.36 |
| hybrid_parent_child | 78 | 73.1% | 83.3% | 0.775 | 0.394 | 32.23 |

### 4.2 块级锚点子集（n=26，策略差异的“主战场”）

| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |
|---|---|---|---|---|---|
| naive | 26 | 65.4% | 84.6% | 0.734 | 10.23 |
| hybrid | 26 | 69.2% | 88.5% | 0.769 | 25.67 |
| hybrid_parent_child | 26 | 73.1% | 88.5% | 0.798 | 32.76 |

### 4.3 结果解读

- **naive（词法 overlap 打分，全父块）最弱**：hit@1 61.5%、MRR .696。overlap 分数无长度归一，
  多文档下易被命中词较多的长文本抢前排；
- **hybrid（BM25，全父块）全面胜出 naive**：hit@1 +9pp、hit@4 85.9% 三档最高、MRR +.072。
  BM25 的 idf + 长度归一显著提升词法精度 —— 这是“混合检索 > 朴素检索”的最直接证据；
- **parent_child（子块召回 + 父上下文注入）精度最优**：hit@1 73.1%、MRR .775 为三档最高，
  块级子集 MRR **.798**（naive .734）。子块粒度让正确答案**更快排到首位**（MRR/hit@1 领先），
  这是“首条引用即命中”的关键体验指标；代价是极端宽召回上 hit@4（全量 83.3%）略低于 hybrid——
  产品上可解释为：需要精准引用选 pc，需要最大召回宽口径选 hybrid，两者都优于 naive；
- **块级视图才见真章**：全量视图被“单父块小文档”的平凡命中稀释（其中 50 条只测单父块文档，天然无法区分块粒度）；26 条块级子集上 naive→pc 的 hit@1 为 65.4%→73.1%（+7.7pp）、MRR .734→.798（+.064）。也就是说 **chunk 粒度差异只有在多父块文档上才可测**，反过来证明“评测必须先于检索优化”——否则会误判三档策略表现一致；
- **延迟**：语料 341 块下，BM25 全内存线性扫描已到 25–32ms（naive 10ms）；这是真实的扩展性瓶颈，
  语料进一步增大时需倒排索引或预计算 TF/DF（下一步优化项）。

### 4.4 局限（面试务必主动说明）

1. 当前 `lexical-only`：向量召回/重排未参与；hybrid 的 RRF+向量、pc 的子块向量召回优势尚未体现。
   配 `DEMO_EMBED_*` 后可复现 `mode: embedding` 的对比；
2. 生成侧（忠实度/相关度/TTFT）未跑（需 `--judge` 与聊天凭据）；
3. 语料主题以中文产品/客服/SaaS 为主，繁体中文字文档与英文文档（`build-multi-tenant-*`）在词法
   only 下与简体 query 不匹配，属于已知检索边界。

---

## 5. 待办与可复现清单

- [x] 语料扩到多父块规模（10 篇 / 56 父块 / 341 chunk）
- [x] 金标扩到 78 条（新增 28 条手写，带 `"review": true` 标记，覆盖 6 篇多父块长文）——**请复核新增条目**
- [x] 块级锚点指标 hit@1 / hit@4 / MRR 及 `metrics_block` 子集
- [ ] （可选）配 `DEMO_EMBED_*`，重跑拿 `embedding` 模式对比表
- [ ] （可选）`run_eval.py --judge` 补生成侧 faithfulness / relevance / TTFT
- [ ] （可选）BM25 倒排索引化，压 retrieve_ms（当前 341 块 ~30ms，线性扫描）
- [ ] 复核后删除新增条目的 `"review": true` 字段，把金标集固化为最终版
