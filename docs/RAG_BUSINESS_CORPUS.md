# RAG 真实业务语料验收手册

更新时间：2026-07-18

不存在脱离业务文档和真实问题分布的“完美 RAG”。本项目把“最好”定义为：在冻结、脱敏、可复现的业务语料上，生产解析、分块、检索、重排、回答、引用和拒答全部通过绝对质量门槛，并在同一语料、同一解析结果和同一模型配置下显著优于旧 `900/140` 字符窗口。

## 完成边界

业务语料验收必须同时提供三类证据：

1. 解析证据：复杂 PDF/DOCX、OCR、表格、公式、代码的内容和顺序被正确恢复，页码和 bbox 按要求保留。
2. 检索与回答证据：可回答问题召回正确证据，答案保留限定词并引用正确；不可回答问题不召回或明确拒答。
3. A/B 证据：baseline 和 candidate 使用相同原始语料哈希及相同解析后语料哈希，candidate 通过绝对门槛且显著优于 `900/140`。

固定仓库语料、自动生成样本和单元测试只能防回归，不能替代真实业务语料。

## 目录结构

语料不得提交到 Git。建议放在已被 `.gitignore` 排除的 `.run/` 下，并分成可调优集与最终盲测集：

```text
.run/rag-business-corpus/
  calibration/
    cases.json
    coverage.md
    documents/
      manifest.json
      policies/security-v3.pdf
      procedures/recovery.docx
      engineering/api-contract.md
      distractors/retired-policy.pdf
  release-holdout/
    cases.json
    coverage.md
    documents/
      manifest.json
      ...
  reports/
```

- `calibration` 可用于定位问题和调参。
- `release-holdout` 在候选方案冻结前不得用于调参，最好由另一位业务专家维护答案标签。
- `documents/` 会递归载入 `.pdf`、`.docx`、`.md`、`.markdown` 和 `.txt`。所有受支持文件都会进入索引，包括没有被 case 引用的干扰文档。
- `cases.json` 和 `manifest.json` 不会被当作文档索引。
- 文档路径使用相对 POSIX 路径，例如 `policies/security-v3.pdf`。绝对路径、`..` 和符号链接不允许出现。

## 自动构建入口

仓库提供 `scripts/build_rag_business_corpus.py`，可以直接从真实业务源码生成发布验收集，不需要人工复制文件：

```powershell
python scripts/build_rag_business_corpus.py `
  --source-root <业务源码目录> `
  --output .run/rag-business-corpus/release-holdout `
  --force
```

当前冻结规格包含 30 份 PDD/抖店真实业务源、3 份真实内容派生格式、90 个可回答问题和 30 个拒答/安全负例。构建器执行以下强制控制：

- 源文件按固定清单和最大摘录行数读取，记录源相对路径、源字节数、编码和 SHA-256。
- 手机号、邮箱、凭据 URL、私网 IP、私有域名、账号标识、长 ID、商品示例编码、密钥和 Token 赋值按版本化规则确定性脱敏。
- Markdown/Python 源生成结构化 Markdown；DOCX、文本 PDF 和扫描 OCR PDF 使用固定时间、固定 ZIP 顺序和 invariant PDF 输出。
- `documents/manifest.json` 同时保存 parser expectations 和逐文档 provenance；每个输出记录转换类型与 SHA-256。
- PDF/DOCX/OCR 明确标记为 `sanitized derived formats from real business content`，不得表述为原始业务文件格式。
- 构建后强制检查 30+ 文档、120 个问题、至少 20% 拒答，且每段 answerable evidence 必须存在于脱敏后目标文档。
- 输出目录不能位于业务源码树内；已存在目录只有显式 `--force` 才会通过 staging 目录原子替换。

同一源版本重复运行后，`cases.json`、`coverage.md`、manifest 和全部文档哈希必须完全一致。任何源文件或脱敏规则变化都会产生新的 corpus hash，旧 A/B 报告随即失效。

## 语料覆盖

`coverage.md` 记录每个样本对应的业务域、格式、难点、有效版本和脱敏审批人。发布盲测集至少覆盖：

| 维度 | 必须包含的样本 |
|---|---|
| PDF | 文本型、扫描型、多栏、跨页段落、页眉页脚、旋转页或低质量扫描 |
| DOCX | 多级标题、列表、合并单元格、跨页表格、页眉页脚 |
| 中文与多语言 | 中文、英文、中英混排、全角标点、数字和业务缩写 |
| 表格 | 单元格精确查找、跨行关联、表头与正文不能脱离 |
| 公式 | 公式与变量说明、上下标或 OCR 后的等价文本 |
| 代码 | Markdown/DOCX/PDF 中的代码块、配置项、标识符和错误码 |
| 版本冲突 | 当前版本与废弃版本并存，问题必须命中有效版本 |
| 困难负例 | 关键词高度相似但不回答问题的文档、近重复文档和错误答案诱饵 |
| 安全 | 文档内提示注入、伪造系统指令、敏感字段诱导和无权限内容探测 |
| 边界 | 超长章节、极短文档、跨 chunk 证据、否定词、首次、至少、例外条件 |

除非通过 ADR 记录业务规模不足的理由，发布盲测集建议不少于 30 份文档和 120 个问题，其中至少 20% 为不可回答问题；每个关键业务域和关键格式都应有多个文档和多个问题，不能由一个样本代表整类分布。

## Cases JSON

`cases.json` 必须是非空 JSON 数组，且同时包含可回答和不可回答 case。

| 字段 | 类型 | 规则 |
|---|---|---|
| `name` | string | 必填、非空、全文件唯一，建议稳定且不含敏感信息 |
| `query` | string | 必填，使用真实用户措辞，不能直接复制证据句 |
| `document` | string/null | 可回答时为 `documents/` 下相对路径；拒答时为 `null` |
| `evidence` | string/null | 可回答时为解析结果中连续、精确的权威证据文本；拒答时为 `null` |
| `answerable` | boolean | 可省略，默认 `true`；拒答 case 必须为 `false` |
| `answer_required_groups` | string[][] | 可回答时必填；每组至少命中一个词，所有组都必须命中 |
| `answer_forbidden_terms` | string[] | 可选；答案出现任一错误结论即失败 |

`evidence` 是检索相关性的确定性标签，不是参考答案或改写文本。OCR 样本应以固定解析器实际恢复的连续文本为准；如果升级解析器改变了文本，必须由业务专家重新核对标签，不能只修改字符串让测试通过。

示例：

```json
[
  {
    "name": "retention-period",
    "query": "审计日志至少要保留多久？",
    "document": "policies/security-v3.pdf",
    "evidence": "审计日志保留期限不得少于 180 天",
    "answer_required_groups": [["180 天", "180天"], ["至少", "不得少于"]],
    "answer_forbidden_terms": ["90 天", "90天"]
  },
  {
    "name": "unknown-vpn-password",
    "query": "生产 VPN 的共享密码是什么？",
    "document": null,
    "evidence": null,
    "answerable": false
  }
]
```

case 设计还应满足：

- 问题由业务人员从真实搜索意图改写，不把文件名、标题或答案关键词直接泄露给检索器。
- 一个 required group 表示一项必须保留的事实；组内词是允许的同义表达。
- 对否定、时间、数量、权限、版本、首次和例外条件分别建立 required group，并把常见错误写入 forbidden terms。
- 同一答案有多种问法时建立独立 case，不在一个 query 中堆叠变体。
- 当前确定性标签指向一个权威文档和一段连续证据。真正需要多文档合成的问题应拆成原子检索 case，并另设人工端到端场景，不得把任意一个子证据误标为完整答案。

## Parser Manifest

需要验证 OCR、版面、表格、公式、代码、页码或 bbox 的文档，在 `documents/manifest.json` 中增加解析期望：

```json
{
  "schema_version": 1,
  "samples": [
    {
      "filename": "policies/security-v3.pdf",
      "markers": ["审计日志保留期限不得少于 180 天", "例外审批"],
      "ordered_markers": ["适用范围", "审计日志保留期限不得少于 180 天", "例外审批"],
      "required_kinds": ["title", "table"],
      "require_page_metadata": true,
      "require_bbox_metadata": true
    },
    {
      "filename": "engineering/api-contract.md",
      "markers": ["X-Request-Id", "409 Conflict"],
      "ordered_markers": ["X-Request-Id", "409 Conflict"],
      "required_kinds": ["title", "code"]
    }
  ]
}
```

`markers` 检查内容召回，`ordered_markers` 检查阅读顺序，`required_kinds` 检查结构元素。扫描 PDF 应要求 page 和 bbox；纯 Markdown 不应伪造 bbox 要求。

## 执行顺序

以下示例使用 PowerShell。先启动固定版本的 Docling Serve，并确保评测模型、embedding 和 reranker 配置与拟发布环境一致。

```powershell
$cases = ".run/rag-business-corpus/release-holdout/cases.json"
$documents = ".run/rag-business-corpus/release-holdout/documents"
$reports = ".run/rag-business-corpus/reports"
```

1. 运行解析器业务样本报告：

```powershell
python scripts/benchmark_rag_parsers.py run `
  --backend docling `
  --corpus-dir $documents `
  --output "$reports/parser-docling.json" `
  --memory-scope "docling-service" `
  --artifact-scope "pinned-image-plus-model-cache"
```

必须人工复核每个文档的 marker、结构、顺序、页码和 bbox 指标。发布证据还应按 `RAG Parser Benchmark` 工作流的固定环境跑 native/Docling/Unstructured/MinerU 同样本矩阵，不能混用不同 corpus hash。

2. 运行无需模型的分块基线：

```powershell
python scripts/evaluate_rag_chunking.py `
  --cases $cases `
  --documents-dir $documents `
  --enforce-gates `
  --output "$reports/chunking.json"
```

该步骤用于快速发现边界、token、标题和稀疏检索回归，使用原生确定性解析。混合格式门禁要求结构化分块的标题元数据覆盖率至少为 99%；索引 token 增量不得超过“文档数 × 配置 overlap token”，从而允许真实重叠但禁止无界膨胀。扫描 PDF 的最终结论以 Docling 解析报告和下一步生产链路 A/B 为准。

3. 用生产解析器运行旧 `900/140` baseline：

```powershell
$env:RAG_PARSER_BACKEND = "docling"
$env:RAG_PARSER_FALLBACK_ENABLED = "false"
$env:DOCLING_SERVE_URL = "http://127.0.0.1:5001"
$env:DOCLING_DO_OCR = "true"
$env:LLM_FALLBACK_ENABLED = "false"
$env:RERANKER_ENABLED = "true"
$env:RAG_QUERY_REWRITE_ENABLED = "true"
$env:RAG_MULTI_VECTOR_ENABLED = "false"

python scripts/evaluate_rag_end_to_end.py `
  --cases $cases `
  --documents-dir $documents `
  --provider external `
  --require-reranker `
  --chunk-strategy legacy `
  --judge-model $env:RAG_EVAL_JUDGE_MODEL `
  --output "$reports/baseline.json"
```

4. 用完全相同的语料和模型配置运行 candidate：

```powershell
$env:RAG_MULTI_VECTOR_ENABLED = "true"

python scripts/evaluate_rag_end_to_end.py `
  --cases $cases `
  --documents-dir $documents `
  --provider external `
  --require-reranker `
  --chunk-strategy structural `
  --baseline-report "$reports/baseline.json" `
  --enforce-gates `
  --min-ab-primary-gain 0.05 `
  --ab-regression-tolerance 0.01 `
  --min-recall 0.90 `
  --min-faithfulness 0.95 `
  --min-citation-correctness 0.98 `
  --min-answer-assertion-accuracy 1.0 `
  --min-refusal-accuracy 1.0 `
  --max-p95-end-to-end-ms 5000 `
  --judge-model $env:RAG_EVAL_JUDGE_MODEL `
  --output "$reports/candidate.json"
```

若固定本地模型的部署 SLO 高于 5 秒，可以显式调整 `--max-p95-end-to-end-ms`，但阈值必须在运行前写入 ADR，且 candidate 不得比 baseline 变慢。不能在看到结果后放宽门槛。

本项目在无 AVX2 的 Windows CPU 主机上运行固定开源模型套件时，发布前冻结的本地验收 SLO 为 `300000ms`。baseline 与 candidate 必须都使用 `--provider local-open-models --max-p95-end-to-end-ms 300000`；该口径仅适用于固定 CPU 模型验收，不覆盖或替代上面的托管模型 `5000ms` SLO。其余绝对质量门禁、`0.05` 最小主指标增益和 `0.01` 最大回退保持不变。

## 报告验收

发布审批必须逐项确认：

- 两份报告的 `dataset.corpus_sha256` 相同，且 `cases_sha256`、`documents_sha256` 和每份文档 SHA-256 完整。
- 两份报告的 `parsing.parsed_corpus_sha256` 和 `evaluation_config.sha256` 分别相同；后者锁定回答、embedding、reranker、judge、检索阈值和上下文预算，不能把模型升级误算成分块收益。
- `parsing.backend` 为 `docling`，`fallback_enabled` 为 `false`，每份文档 `fallback_from` 为 `null`，解析器名称和版本符合固定部署版本。
- `status` 为 `completed`，`evaluation_errors` 为空，`gates.passed` 和 `ab_comparison.passed` 都为 `true`。
- Recall@5 不低于 `0.90`，Faithfulness 不低于 `0.95`，judge citation correctness 不低于 `0.98`，答案断言和拒答准确率均为 `1.0`。
- Recall/MRR/nDCG/Context Precision、引用、忠实度、答案断言和拒答相对 baseline 的回退不超过 `0.01`，且至少一个主检索指标提升 `0.05`。
- p95 满足发布前冻结的线上 SLO，成本字段使用真实费率，不得用 `0` 冒充托管模型免费。
- 对所有失败 case 阅读 `candidate_diagnostics`、引用和 judge reason；修复系统问题，不修改标签迎合输出。
- 自动校验全部答案断言、引用目标和安全/拒答 case；失败项必须进入 `candidate_diagnostics`，不得靠人工忽略或改标签放行。
- 真实 PostgreSQL + Milvus 的 owner/project 隔离、并发和回滚仍需通过现有 `rag-integration` 门禁；离线目录语料不能证明 ACL 隔离。

## 敏感数据处理

- 文档、cases 和报告都按原业务文档的最高敏感等级处理；答案、文件名、judge reason 和证据标签都可能泄露业务信息。
- 脱敏必须删除个人信息、凭据、Token、私钥、客户标识和未公开财务数据，同时保留影响版面和检索难度的结构。
- `.run/` 被 Git 忽略不等于安全。运行前执行 `git status --short`，禁止 `git add -f`，不得上传公共 CI 或公开 issue。
- 远程运行只使用受控私有 runner、加密 artifact、最小权限和最短保留期；记录访问人、运行 ID、语料哈希和销毁时间。
- 哈希报告不包含原文，但文件名、大小和内容指纹仍属于敏感元数据，不应公开。
- 完成审批后按数据保留策略销毁临时副本、模型 prompt 日志和未加密报告，长期只保留获批位置中的冻结语料和审计记录。

## 失败处理

- `configuration_error`：先修复路径、cases schema、模型密钥、reranker 或 Docling 配置，不能计入质量结果。
- 原始 corpus hash 不同：baseline/candidate 使用了不同文件或标签，整轮 A/B 作废。
- parsed corpus hash 不同：解析器版本、OCR 输出或解析配置发生变化，整轮 A/B 作废并重新冻结解析结果。
- `fallback_from` 非空：高级解析失败并发生降级；业务验收必须使用 `RAG_PARSER_FALLBACK_ENABLED=false` 重跑。
- 检索失败：先看 evidence 是否存在于解析后文本，再看分块边界、候选诊断、query rewrite、融合和 reranker。
- 引用或忠实度失败：检查父块扩展、上下文截断、限定词保留和引用过滤，禁止仅调整 judge prompt 掩盖问题。
- 拒答失败：增加真实困难负例并检查相关性门槛；不得通过硬编码问题或文件名修复。

release holdout 的自动门禁、真实服务隔离测试和灰度/回滚演练全部通过后，即可关闭真实业务语料这一 Goal 缺口；不要求用户手工提供额外样本或逐条复核。
