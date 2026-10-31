# RAG Research Explorer — 项目概览

一个本地运行的学术研究探索工作台：从 OpenAlex 采集 2021–2026 年 RAG 相关论文，做去重、相关性初筛、BM25 检索、种子论文探索、文献收藏、结构化比较与 AI 辅助理解。

## 技术栈

- 后端：Python 3.12 + Flask + Jinja2。
- 存储：SQLite + FTS5（`papers.db` 主索引，`collections.db` 收藏）。
- 检索：SQLite FTS5 BM25。
- 推荐：标准库 TF-IDF（标题/摘要余弦相似度 + 作者重合）。
- 前端：HTML / CSS / 原生 JS，ECharts 仅用于分析图表（CDN）。
- AI：DeepSeek `deepseek-chat`，仅使用 title / abstract / authors / metadata。
- 数据源：OpenAlex。

## 主要功能

1. 语料采集与清洗：按年份多查询词采集、跨轮去重、版本识别与人工复核、相关性初筛。
2. 学术搜索：BM25、年份 / 文献类型 / 初筛状态组合筛选、分页、搜索词高亮、版本折叠。
3. 论文详情：元数据、摘要、版本信息、Cite（APA/IEEE）、AI 单篇分析。
4. Seed Paper Exploration：可解释的 TF-IDF 相关论文推荐与连续探索。
5. Reading Collections：默认 `My Library`、Quick Save、阅读状态、导出引用、批量比较。
6. AI 工作流：单篇 TL;DR / Contributions / Methodology / Limitations，多篇 Research Overview、连续追问、结构化 Paper Comparison。
7. Research Analytics：真实数据计算的 Publication Trend、Top Topics、Emerging Keywords、Top Authors。
8. Research Map：论文-主题关系与文本相似度关系（明确不是引用关系）。

## 数据规模与口径

- 候选论文：1431 篇（去重后）。
- 初筛状态：included 701 / excluded 437 / uncertain 293。
- 版本组：72 个（确认同一作品），另有人工复核清单。
- 所有统计只代表当前本地候选语料，不代表完整 RAG 文献；2026 年为不完整年份。

## 关键实现细节

- 摘要由 OpenAlex `abstract_inverted_index` 按词位置重建。
- 版本识别：DOI 一致优先；无 DOI 按规范化标题；冲突不删除；短标题需强证据。
- AI 输入只含 Abstract / Metadata；提示词把论文内容视为不可信，引用 ID 由后端生成。
- Markdown 先转义再渲染，避免 XSS。
- API Key 只从环境变量读取，不进入前端或日志。

## 运行

```bash
source .venv/bin/activate
python app.py          # http://127.0.0.1:5000
python -m unittest discover -s tests -v
```

数据管线（一次性/增量）：

```bash
python scripts/fetch_papers.py --strategy --limit 100
python scripts/merge_corpus.py --review data/version_review.json
python scripts/inspect_data.py
python scripts/screen_corpus.py
python scripts/build_db.py
```

## 已知边界

- 不抓取/解析全文，不绕过付费墙；AI 分析仅基于摘要与元数据。
- 作者统计按姓名字符串计数，无 ORCID 身份合并。
- Research Map 的 paper-paper 边是文本相似度，不是引用关系。
- 推荐与检索评测集有人工标注框架，但当前推荐评估尚未完成人工标注，未报告 P@K。
