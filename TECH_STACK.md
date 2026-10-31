# 技术栈与数据字段

## 总体技术选型

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 数据源 | OpenAlex | 主元数据、引用数、出版来源；arXiv/Semantic Scholar 未接入 |
| 语言 | Python 3.12 | CLI 脚本 + Flask 应用 |
| 存储 | SQLite + FTS5 | `papers.db`（主表 + 全文索引）、`collections.db`（收藏） |
| 检索 | BM25 | 由 SQLite FTS5 `MATCH ... ORDER BY rank` 实现，未重写 |
| 推荐 | 标准库 TF-IDF | 标题/摘要余弦相似度 + 作者重合，未引入 scikit-learn |
| Web | Flask + Jinja2 | 服务端渲染 + JSON API |
| 前端 | HTML / CSS / 原生 JS | ECharts 通过 CDN 用于分析图表 |
| AI | DeepSeek API | `requests` 调 chat completions，只吃 Abstract/Metadata |

未引入：向量数据库、React/Vue、scikit-learn、D3.js、其他 AI SDK。

## 关键依赖

`Flask`、`requests`、`python-dotenv`；其余为标准库（`sqlite3`、`json`、`re`、`collections`、`hashlib`、`threading`）。ECharts 为浏览器端 CDN 脚本，不是 Python 依赖。

## 数据库

`data/papers.db`：

- `papers`：`paper_id`(主键)、`title`、`abstract`、`year`、`publication_date`、`doi`、`venue`、`type`、`language`、`cited_by_count`、`authors_json`、`biblio_json`、`source`、`normalized_title`、`matched_queries_json`、`matched_years_json`、`run_ids_json`、`openalex_ids_json`、`dedup_status`、`relevance_status`。
- `papers_fts`：FTS5 虚拟表，覆盖 `title` / `abstract`，`paper_id` 为 UNINDEXED 关联键。
- `conflicts`：标题相同但字段冲突的记录组。

`data/collections.db`：

- `collections`：收藏夹。
- `collection_items`：收藏夹与论文的关联，含 `added_at`、`reading_status`。

## 关键数据文件

- `data/corpus.json`：跨轮去重后的候选语料，含版本组与冲突组。
- `data/screened_corpus.json`：相关性初筛结果（included / excluded / uncertain，及 doc_type）。
- `data/version_review.json`：人工版本复核清单。
- `eval/queries.json`、`eval/seed_papers.json`：检索与推荐评测集。

## 实现要点

- 搜索、推荐、统计、收藏、AI 均在 `services/` 独立 Service 中，Routes 只做参数校验与调用。
- 相关性初筛状态统一读取 `screened_corpus.json`，不直接使用 `papers.relevance_status`。
- 版本识别：DOI 一致优先；无 DOI 按规范化标题；冲突保留待核验；短标题需额外证据。
- AI 引用由后端根据输入构建 `P1…Pn` 映射，不从模型输出解析；论文内容被视为不可信输入。
