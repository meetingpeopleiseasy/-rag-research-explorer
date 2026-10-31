# RAG 论文智能搜索与研究脉络分析平台

课程项目：面向 **2021–2026 年 RAG（Retrieval-Augmented Generation）相关论文** 的智能搜索与研究脉络分析平台。

## 当前进度

已实现：

- 数据源 **OpenAlex**：2021–2026 年 RAG 相关论文元数据。
- 按年份 + 多个查询词批量采集（策略集中配置在 `fetch_papers.py` 的 `QUERY_STRATEGY`）。
- 每轮采集独立保存原始响应与 run 记录，不再覆盖历史语料。
- 跨轮次去重与冲突检查（DOI 优先、无 DOI 按规范化标题、冲突保留待核验）。
- 数据检查、SQLite + FTS5 入库与全文检索。
- 候选语料相关性初筛（`scripts/screen_corpus.py`，区分 included / excluded / uncertain / pending，并标注文献类型）。
- 本地 Flask Web 应用：Search、Paper Detail、Seed Paper Exploration、Reading Collections、Analytics、Research Map。
- DeepSeek AI：单篇分析、多篇 Research Overview、连续追问、Paper Comparison。
- 检索评测集（18 查询）与推荐评估框架（6 种子）。
- 113 项单元测试。

尚未实现：

- 全文获取与全文分析（当前 AI 只基于 Abstract / Metadata）。
- arXiv 数据源补充。
- 初筛结果的完整人工核验（初筛不能当作正式语料）。

## 数据源角色

| 数据源 | 角色 | 主要限制 |
| --- | --- | --- |
| OpenAlex | 主元数据、引用数、出版来源 | 主题检索需调试，部分字段缺失 |
| arXiv | 补充预印本与摘要（后续） | 覆盖偏预印本，引用数据不足 |
| Semantic Scholar | 可选补充（后续） | 当前申请被拒，匿名请求受限 |

## 三种语料概念

项目把数据分成三个层次，避免把“抓到的记录”误当成“正式语料”：

1. **原始记录**：`data/raw/` 中逐页保存的 OpenAlex 原始响应，以及 `data/runs/run_<run_id>.json` 中每轮规范化后的记录（含 `matched_queries`、`matched_years`、`run_id`）。
2. **候选语料**：`data/corpus.json`，由 `merge_corpus.py` 跨轮去重合并而成，保留 `dedup_status`、`conflicts`、`relevance_status`（默认 `pending`）。
3. **正式语料**：尚未生成。`scripts/screen_corpus.py` 只做规则初筛并写入 `data/screened_corpus.json`，把每条候选标记为 `included` / `excluded` / `uncertain` / `pending`；正式语料仍需人工核验后才能确定。

## 目录结构

```text
.
├── README.md
├── TECH_STACK.md
├── PROJECT_OVERVIEW.md
├── requirements.txt
├── .env.example
├── app.py                  # Flask 入口
├── routes/                 # 页面与 API 路由
├── services/               # 搜索/推荐/统计/收藏/AI Service
├── templates/              # Jinja2 页面
├── static/                 # CSS / JS
├── scripts/
│   ├── fetch_papers.py     # 按策略批量采集 OpenAlex 数据
│   ├── merge_corpus.py     # 合并多轮 run，生成去重候选语料
│   ├── inspect_data.py     # 统计重复、年份覆盖、摘要缺失
│   ├── build_db.py         # 候选语料入库（SQLite + FTS5）
│   ├── search_papers.py    # FTS5 全文检索
│   ├── screen_corpus.py    # 相关性初筛（不覆盖 corpus.json）
│   ├── eval_search.py      # 导出 Top-10 并计算已标注查询的指标
│   ├── eval_recommendation.py # 推荐变体评估
│   └── corpus.py           # 去重/冲突/规范化标题共享逻辑
├── eval/
│   ├── queries.json        # 检索评测集（含人工标注字段）
│   ├── seed_papers.json    # 推荐评估种子
│   └── results_top10.json  # 每个查询的 Top-10 导出
├── tests/
│   ├── test_pipeline.py    # 去重/入库测试
│   ├── test_search.py      # 检索输入处理测试
│   ├── test_screen.py      # 初筛测试
│   ├── test_eval.py        # 评测指标测试
│   ├── test_eval_recommendation.py
│   ├── test_dedup_display.py
│   ├── test_versions.py
│   ├── test_recommendation.py
│   ├── test_web.py
│   ├── test_ai.py
│   ├── test_overview.py
│   ├── test_collections.py
│   └── test_analytics.py
└── data/                   # 生成的数据（已 gitignore）
    ├── raw/                # 每页原始 API 响应
    ├── runs/               # 每轮规范化记录
    ├── corpus.json         # 跨轮去重后的候选语料
    ├── screened_corpus.json# 相关性初筛结果
    ├── version_review.json # 人工版本复核
    ├── collections.db      # 收藏夹数据库
    └── papers.db           # SQLite + FTS5 数据库
```

## 快速开始

```bash
# 1. 安装依赖（核心只需 requests；python-dotenv 用于读取 .env）
python -m pip install -r requirements.txt

# 2.（可选）在 .env 中配置 OPENALEX_API_KEY

# 3. 按策略批量采集（2021–2026，多查询词）
python scripts/fetch_papers.py --strategy --limit 100

# 4. 合并多轮结果，生成候选语料
python scripts/merge_corpus.py

# 5. 检查重复、年份覆盖与摘要缺失
python scripts/inspect_data.py

# 6. 相关性初筛（生成独立文件，不覆盖 corpus.json）
python scripts/screen_corpus.py --dry-run     # 先看报告
python scripts/screen_corpus.py               # 写入 data/screened_corpus.json

# 7. 建库 + 检索
python scripts/build_db.py
python scripts/search_papers.py '"retrieval augmented"' --limit 10

# 8. 导出评测 Top-10（用于人工标注）
python scripts/eval_search.py
```

单个查询的临时抓取（不按策略）：

```bash
python scripts/fetch_papers.py --query "RAG evaluation" --year 2024-2026 --limit 50
```

## 本地 Web 应用

Flask 产品原型位于 `app.py`、`routes/`、`services/`、`templates/`、`static/`。

```bash
source .venv/bin/activate
python app.py
# 打开 http://127.0.0.1:5000
```

页面工作流：Search → Results → Paper Detail → AI-assisted understanding。搜索复用现有 BM25 + FTS5，结果页支持分页、年份筛选、搜索词高亮和版本组折叠；详情页展示论文元数据、摘要和版本信息，并按需调用 DeepSeek 生成 TL;DR、Key Contributions、Methodology、Limitations；搜索结果页可选择多篇论文生成 Research Overview 或提问。

接口：`GET /api/search`、`GET /api/paper/<paper_id>`、`POST /api/ai/paper-analysis`、`POST /api/ai/research-overview`、`POST /api/ai/qa`。DeepSeek Key 仅从环境变量读取，不写入前端或日志；AI 分析只使用标题、作者、摘要和元数据，并把论文内容视为不可信输入。

## Seed Paper Exploration

论文详情页和结果页可进入 `Explore from this paper`，打开 `/explore/<paper_id>`。推荐由 `services/recommendation_service.py` 基于本地语料计算：标题 TF-IDF 相似度、摘要 TF-IDF 相似度和作者重合作为可解释的推荐依据，综合分数仅用于系统内部排序，不表示学术相关性概率。

- 排除种子论文本身，以及已确认的同一论文版本；不同 `different_work` 记录独立保留。
- 默认优先展示 `included`，`uncertain` 作为次级结果并带状态标记，`excluded` 默认不进入，可通过 `include_excluded=1` 显式查看。
- 短标题、缺失摘要不会产生虚假相似度；结果不足时如实展示，不补低质量结果。
- 推荐使用标准库 TF-IDF 实现，未引入 scikit-learn 或其他新依赖。

AI 输出使用前端 `safeMarkdown` 渲染：先转义 HTML 再转换 Markdown，避免 XSS。

## Reading Collections 与 Paper Comparison

- 集合持久化在独立的 `data/collections.db`，不修改 `papers` 主表；支持创建、重命名、删除、加入/移除论文，删除集合不会删除论文或原始语料。
- 可从论文详情页、搜索结果页和 Explore 页把论文加入集合；集合页支持多选后做结构化比较。
- `POST /api/ai/compare` 对 2–5 篇论文生成固定维度的比较表，并用 `P1…Pn` 关联证据；模型只依据 title/abstract/metadata，摘要不足时返回 `insufficient_information`。
- Research Overview 尝试解析为结构化 JSON，解析失败时保留原文并标记为未结构化，前端仍安全渲染。

推荐评估集在 `eval/seed_papers.json`（6 个主题种子），`scripts/eval_recommendation.py` 对比 title-only / abstract-only / combined / BM25 baseline。当前尚无人标注，因此不计算 Precision@K。

## Analytics 与 Research Map

- `/analytics` 用 ECharts 展示 Publication Trend、Top Research Topics、Emerging Keywords、Top Authors；所有数字由 `services/analytics_service.py` 从本地语料计算。
- Emerging Keywords 对比两个年份区间（默认 2021–2023 vs 2024–2026），小基数关键词带 `small_base` 标记，不会把 +35x 这类增长当作可靠趋势。
- `/map/<paper_id>` 展示 Seed Paper 的 Research Map：paper-paper 边标记为 similarity，paper-topic 边来自文本/关键词提取，不冒充引用关系。
- 搜索结果的初筛状态现在统一来自 `screened_corpus.json`，不再显示全量 `pending`。

## 语料构建规则

**单次关键词搜索不等于完整语料。** 当前流程只产出“候选语料”：

1. 检索范围：OpenAlex works，按年份分别过滤 `publication_year:2021` 到 `2026`。
2. 检索策略：`QUERY_STRATEGY` 按年份配置多个候选查询词（如 2021 用 `RAG`、`retrieval-augmented language model`；2024–2026 用 `RAG`、`retrieval-augmented generation`、`RAG evaluation`）。这些是候选检索词，不是最终纳入标准。
3. 去重规则：DOI 一致优先合并；无 DOI 时按规范化标题发现重复候选；标题相同但年份、作者或出版来源冲突时保留双方并记录冲突；标题相同但 DOI 不同（或部分缺失 DOI）时保留并标记为待核验标题重复组，不静默删除。
4. 溯源记录：每篇候选保留 `matched_queries`、`matched_years`、`run_ids` 和 OpenAlex ID。
5. 相关性初筛：`screen_corpus.py` 用可配置的标题/摘要规则把候选标记为 `included` / `excluded` / `uncertain` / `pending`，同时区分期刊论文、会议论文、预印本、综述、软件/数据集等文献类型。缩写歧义、摘要缺失、标题与摘要证据冲突等情况标记为 `uncertain`，不会轻率自动纳入或排除。

## 数据字段（OpenAlex 抓取子集）

| 字段 | 说明 |
| --- | --- |
| id / paperId | OpenAlex 作品主键 |
| doi | DOI（可能缺失） |
| title | 标题 |
| publication_year | 发表年份 |
| publication_date | 发表日期 |
| abstract | 由 abstract_inverted_index 重建的摘要（可能缺失） |
| authorships | 作者信息 |
| cited_by_count | 被引次数 |
| primary_location | 出版来源（期刊/会议等） |
| biblio | 卷/期/页码 |
| type | 作品类型 |
| language | 元数据语言 |

## 已验证的 OpenAlex API 行为

- 端点：`GET https://api.openalex.org/works`。
- 认证：可选，`Authorization: Bearer <key>`；无 Key 使用匿名共享配额（10 req/s）。
- 参数：`filter=publication_year:2021-2026`、`search=<关键词>`、`select=<字段>`、`per-page`（≤100）、`page`（基础分页上限 10000 条）。
- 摘要以 `abstract_inverted_index` 返回，需按词语位置重建；OpenAlex 不直接提供纯文本摘要。
- 搜索请求计费高于普通过滤请求；批量抓取前留意每日配额。

## 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：DOI 重复合并、无 DOI 标题重复合并、标题冲突保留、标题重复标记、跨年份合并、空摘要入库、检索输入处理、相关性初筛、评测指标（严格/宽松）、重复展示分组、版本识别。

## 检索质量评估

评测集在 `eval/queries.json`，包含 18 个典型查询，覆盖基础 RAG、检索方法、RAG 评估、多模态 RAG、幻觉问题和早期研究。每个查询包含 `query_id`、`query`、`intent`、`theme` 和 `annotations`。

使用方式：

1. 运行 `python scripts/eval_search.py`，把每个查询的 BM25 Top-10 导出到 `eval/results_top10.json`，便于人工标注。
2. 人工查看每个查询的结果，在 `eval/queries.json` 的 `annotations` 里以 `{"<paper_id>": 2|1|0}` 记录相关性（2 严格相关，1 宽松相关，0 不相关）。
3. 重新运行 `python scripts/eval_search.py`，对有标注的查询计算 Precision@5 和 Precision@10。

指标口径：严格相关为 `relevance == 2`，宽松相关为 `relevance >= 1`。由于人工标注不完整，`Precision@K` 的分母是该查询 Top-K 中已有人工标注的结果数，而不是固定 K；未标注结果既不视为相关也不视为不相关，从分子分母中排除。已标注结果为 0 时指标为 `None`，不会报告成 0。导出结果会同时记录 BM25 分数、排名、已标注条数和近似同分组，便于核对。

## 检索结果的重复展示

`search_papers.py` 不会删除或修改底层论文记录，只在展示层做去重提示：

- DOI 一致或 OpenAlex ID 一致的记录视为同一数据库记录，合并为一组展示，并列出组内全部 OpenAlex ID。
- 依据 `corpus.json` 的版本组：`confirmed_same_work` 折叠为一条展示，优先显示有正式出版信息（非 arXiv/SSRN/Zenodo）、DOI 和摘要更完整的代表版本，并列出全部版本 ID。
- `suspected_same_work` 只标记不合并，保留人工核验入口。
- 仅标题相同但 DOI 不同（或部分缺失 DOI）的记录保留原样，标记为“疑似重复”，不合并。
- 标题相似度不作为合并依据：版本识别要求规范化标题完全一致，且作者或摘要证据充分；标题相同但作者和摘要明显不同的记录判为不同作品，不归组。
- 短标题碰撞：单字标题（如 `rag`、`rags`）不会仅凭标题相同就创建疑似版本组；只有当 DOI 明确指向同一作品、存在可靠的预印本-正式出版关联，或作者与摘要同时高度一致时才可归组。
- 版本识别与相关性筛选是两件事：`rag` / `rags` 等与 RAG 研究无关的记录由 `screen_corpus.py` 按“无 RAG 信号”标记为 `excluded`（单字歧义标题额外带 `short_title_ambiguous` 标记），不会仅凭标题 `RAG` 就判定研究领域。
- 人工审核覆盖：`merge_corpus.py --review data/version_review.json` 读取人工审核结果覆盖自动判定。`same_work` 升级为确认同一作品并折叠展示；`different_work` 解除疑似版本关系、独立展示；`uncertain` 保持疑似标记、不折叠；`pending` 不覆盖自动结果。人工审核只写入版本组元数据，不修改论文标题、摘要等字段。

## 已知限制与待办

- OpenAlex Key 可选；不配 Key 时匿名共享配额可能被同一网络的其他用户耗尽。
- 初筛只是规则初判，正式语料仍需人工核验。
- 版本识别目前只在规范化标题完全一致时进行，使用作者/摘要重叠阈值做启发式判断；阈值与个别疑似组仍需要人工复核。
- Semantic Scholar 申请被拒，暂不作为数据源；arXiv 补充尚未接入。
- `TECH_STACK.md` 中 SQLite 表字段说明尚未与新增列完全同步。

