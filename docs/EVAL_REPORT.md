# RAG 评测报告（EVAL REPORT）

> 生成方式：`evals/run_eval.py`。原始数字源文件 `evals/EVAL_RESULTS.json` / `EVAL_RESULTS.md`
> （看板 `/dashboard` 读取前者）。语料位于 `producttext/`。
> 评测对象：AI 产品知识助手的检索与生成链路。

---

## 1. 目的与结论

评测回答三个问题：

1. 不同检索策略（naive / hybrid / hybrid_parent_child）在同一份金标集上谁更准、快多少；
2. 生成答案是否正确、是否有证据支撑、引用是否落到金标文档、无答案时是否拒答；
3. 把“混合检索 / 父子分块 / 拒答护栏”从形容词变成**有数字支撑**的结论，并诚实标注跑分边界。

**当前结论（10 文档语料，78 条手写金标，词法-only）：**

- 词法检索的精度排序为 **parent_child ≥ hybrid > naive**：
  - hit@1：naive 61.5% → hybrid 70.5% → parent_child 73.1%；
  - MRR：naive .696 → hybrid .768 → parent_child .775（在**块级锚点子集**上 pc 达 **.798**，naive .734）；
  - 即在“第一条引用就要命中”的对话体验指标上，父子分块显著领先 naive，BM25 混合次之。
- **生成侧（24 条抽样，lexical-only 检索 + `hybrid_parent_child`）**：answer correctness **97.9%**、
  faithfulness **84.5%**、answer relevance **100%**、citation accuracy **92.7%**、citation coverage **95%**、
  refusal recall **100%**；4 道域外问题全部正确拒答，平均 TTFT 约 **1.67s**。
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

### 2.4 生成侧（`--judge`）

生成集位于 `evals/generation_cases.json`：20 条有答案题按 8 篇金标文档分层，另加 4 条域外无答案题。
所有题目复用产品真实的 `stream_answer()` 链路与 `hybrid_parent_child` 策略，保证测的是实际行为而不是旁路实现。

- **answer correctness / faithfulness / answer relevance**：judge 基于检索证据、期望要点和回答打分（0–1）；
- **citation presence / accuracy / coverage**：从回答中的 `[1]` / `[Source 1]` 确定性解析引用，再核对引用编号与金标文档；
- **refusal recall**：无答案题必须触发显式拒答或语义等价的无依据拒答；有答案题若误拒答计入 false refusal；
- **avg TTFT / end-to-end**：记录首 token 与完整请求耗时。

默认 judge 沿用聊天模型，也可通过 `--judge-model` 指定；对会输出 reasoning token 的网关，评测器带空响应重试并使用 JSON mode。

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
.venv\Scripts\python.exe evals/run_eval.py --judge --judge-model deepseek-flash
```

输出：刷新 `evals/EVAL_RESULTS.json` 与 `evals/EVAL_RESULTS.md`。

---

## 4. 当前快照（2026-09-10 · 10 篇文档语料 · lexical-only）

语料：`producttext/` 10 篇文档 → seed 后 56 父块 / 341 条 chunk（含父子树）。
金标集：78 条手写，其中 26 条为**块级锚点**（真正会拉开三档策略的子集）。
Generation eval：24 条（20 有答案 + 4 无答案）；generator `deepseek-v4-flash`，judge `deepseek-flash`。

### 4.1 全量金标（n=78）

| strategy | n | hit@1 | hit@4 | MRR | avg top score | avg retrieve ms |
|---|---|---|---|---|---|---|
| naive | 78 | 61.5% | 82.0% | 0.696 | 0.435 | 9.97 |
| hybrid | 78 | 70.5% | 85.9% | 0.768 | 0.433 | 25.45 |
| hybrid_parent_child | 78 | 73.1% | 83.3% | 0.775 | 0.394 | 31.89 |

### 4.2 块级锚点子集（n=26，策略差异的“主战场”）

| strategy | n | hit@1 | hit@4 | MRR | avg retrieve ms |
|---|---|---|---|---|---|
| naive | 26 | 65.4% | 84.6% | 0.734 | 10.11 |
| hybrid | 26 | 69.2% | 88.5% | 0.769 | 25.34 |
| hybrid_parent_child | 26 | 73.1% | 88.5% | 0.798 | 32.43 |

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

### 4.4 生成侧结果（n=20 有答案 + 4 无答案）

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

结果说明：事实型题目和拒答护栏稳定；剩余失败主要来自 lexical-only 在“RAG 评估指标”“Agent 模块”等问题上
召回错块，导致回答正确率下降/faithfulness 被判低，或引用了文档内但非目标段的来源。这正是下一阶段升级
embedding/重排序的输入，而不是 Prompt 参数微调的问题。

### 4.5 局限（面试务必主动说明）

1. 当前 `lexical-only`：向量召回/重排未参与；hybrid 的 RRF+向量、pc 的子块向量召回优势尚未体现。
   配 `DEMO_EMBED_*` 后可复现 `mode: embedding` 的对比；
2. 生成侧已跑 24 条，但 judge 仍是 LLM 评分；引用和拒答为确定性指标，faithfulness/correctness 会受 judge model 波动影响；
3. 语料主题以中文产品/客服/SaaS 为主，繁体中文字文档与英文文档（`build-multi-tenant-*`）在词法
   only 下与简体 query 不匹配，属于已知检索边界。

---

## 5. 待办与可复现清单

- [x] 语料扩到多父块规模（10 篇 / 56 父块 / 341 chunk）
- [x] 金标扩到 78 条（新增 28 条手写，带 `"review": true` 标记，覆盖 6 篇多父块长文）——**请复核新增条目**
- [x] 块级锚点指标 hit@1 / hit@4 / MRR 及 `metrics_block` 子集
- [ ] （可选）配 `DEMO_EMBED_*`，重跑拿 `embedding` 模式对比表
- [x] `run_eval.py --judge` 生成侧 answer correctness / faithfulness / citation / refusal / TTFT
- [ ] （可选）BM25 倒排索引化，压 retrieve_ms（当前 341 块 ~30ms，线性扫描）
- [ ] 复核后删除新增条目的 `"review": true` 字段，把金标集固化为最终版
