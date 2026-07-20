# RAG Goal 完成审计

更新时间：2026-07-20

本轮完成方案是 `structural parent-child + parent multi-vector`。Chonkie SemanticChunker 保留为离线实验，不作为生产发布必经路径：在本机无 AVX2 CPU 上，33 份业务文档的 semantic boundary embedding 单独运行约 8 小时仍未产生报告，继续运行不符合本轮“快速完成”要求。该进程已终止，未生成的结果不计入任何门禁。

## 完成结论

| 要求 | 状态 | 证据 |
|---|---|---|
| 自动接入真实业务语料，不要求用户手工整理 | 通过 | `scripts/build_rag_business_corpus.py` 从 30 份 PDD/抖店业务源生成 33 份混合格式文档、90 个可回答 case 和 30 个拒答/安全 case |
| 确定性、可追溯和脱敏 | 通过 | cases `f07590c0...742d`、documents `eb013567...634`、corpus `0475b2c7...f9c`；manifest `0f12e8ad...00c`、coverage `cf7a0bb9...f5e`；逐源/输出 SHA-256、编码、转换与脱敏计数完整 |
| 结构/版面/OCR 解析 | 通过 | Docling 1.26.0 对业务 parser 样本的成功率、marker、结构、阅读顺序、页码和 bbox 均为 `1.0`，无 fallback |
| 新分块显著优于 `900/140` | 通过 | 120-case 同语料 A/B：MRR `0.5843 -> 0.6622`、nDCG `0.6384 -> 0.7054`、Context Precision `0.2648 -> 0.3269`、引用目标 `0.4444 -> 0.5444` |
| 索引质量与容量约束 | 通过 | 标题元数据覆盖 `0.9952`；索引 token 仅增加 `808`，低于门禁上限 `3300`；chunking gates 无失败 |
| 混合召回、rerank、父块、引用与拒答 | 通过 | 固定开源模型端到端门禁及真实 PostgreSQL + Milvus v4 集成 job 均绿色 |
| 项目/owner 隔离、版本化索引、灰度与回滚 | 通过 | CI #7/#8 的 PostgreSQL + Milvus owner 过滤、并发与 p95；本地索引激活/回滚和故障注入测试 |
| 生产默认启用已验证路径 | 通过 | `RAG_CHUNK_STRATEGY=structural`、`RAG_MULTI_VECTOR_ENABLED=true`；运行时仍可关闭 multi-vector 快速回滚 |
| 不依赖人工阻塞步骤 | 通过 | 语料构建、哈希、解析、分块、答案断言、引用、拒答、安全扫描和测试均由脚本/门禁执行 |

## 真实业务证据

### 语料

- 输出：`.run/rag-business-corpus/release-holdout`。
- 格式：Markdown/代码、确定性 DOCX、文本 PDF、OCR PDF。
- 构建器只读业务源，`--force` 仅可替换带有效 manifest 的受管目录。
- 重建后 cases、33 份文档及 corpus hash 与完整 baseline 完全一致；新增 parser marker 只改变 manifest hash。
- 文本与元数据扫描未命中手机号、私网 IP、带凭据 URL、私钥或长密钥/Token 赋值。派生二进制格式只使用通过 `assert_sanitized` 的文本。

### 解析器

同一 parser corpus hash：`9a468b1c...78b9`。

| 后端 | 成功率 | Marker | 结构 | 顺序 | 页码 | BBox | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| native | 0.8333 | 0.8333 | 0.8333 | 0.8333 | 0.5 | 0 | 0.529 s |
| Docling 1.26.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 28.580 s |

native 无法解析 OCR PDF；Docling 6/6 成功，服务峰值内存 `2332.78 MB`，固定环境加模型 `2592.67 MB`。最终报告位于 `.run/rag-business-corpus/reports/parser-native.json` 与 `parser-docling.json`。

### 分块与检索

最终 `.run/rag-business-corpus/reports/chunking.json` 使用 corpus hash `0475b2c7...f9c`，所有 gates 通过：

| 策略 | Recall@5 | MRR | nDCG@5 | Context Precision | 引用目标 | Index tokens |
|---|---:|---:|---:|---:|---:|---:|
| legacy `900/140` | 0.8000 | 0.5843 | 0.6384 | 0.2648 | 0.4444 | 45,173 |
| structural parent-child | 0.8333 | 0.6622 | 0.7054 | 0.3269 | 0.5444 | 45,981 |

### 端到端模型

- 本机真实业务 baseline 完成 120/120 case，`evaluation_errors=[]`，Docling 33/33、fallback 0，运行时指纹完整，耗时 `21.444 h`。旧方案 Recall `0.4444`、MRR `0.3815`、nDCG `0.3976`、答案断言 `0.4000`、拒答 `0.7333`、业务 p95 `602.429 s`，证明旧路径不满足发布要求。
- [`RAG Model Quality Gate`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29654495604) 固定模型 A/B 绿色；artifact ID `8432982529`，ZIP SHA-256 `cb59730b98ecaf76c494b92333bb5c82a232ddd35d61b6446cd8e5457db77622`。Candidate Recall/MRR/nDCG `1.0`，Context Precision `0.6583`，Faithfulness、引用、答案断言和拒答均为 `1.0`，p95 `79.646 s`。
- 被终止的本机 semantic candidate 没有 `candidate.json`，不用于声称质量通过。生产选择 structural 是基于真实业务同语料 A/B、固定模型全链路门禁和 semantic 本机成本共同作出的决定。

## 最终验证

- RAG 专项：`48 passed`。
- 后端全量：`298 passed, 7 skipped, 1 failed`。唯一失败是工作区已有 LangGraph 改动中的 `test_specialists_execute_dependency_waves_and_forward_upstream_handoffs`，`contract_version == 2` 断言单独重跑仍失败；与本轮 RAG 文件无关，未越界修改。
- Python compile：通过。
- `git diff --check`：通过。
- 默认配置断言：`structural + multi-vector` 通过。
- 业务语料敏感模式扫描：5 类模式零命中。

本轮不再存在需要用户手工提供语料、逐条抽查或处理环境阻塞的 RAG 步骤。后续若启用 semantic，只作为独立性能实验，不影响当前 structural 生产路径和回滚能力。
