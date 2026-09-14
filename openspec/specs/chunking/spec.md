# chunking Specification

## Purpose

把 MinerU 解析出的 `content_list.json` 转成可检索的 `Chunk`（检索单元）并落库到 MySQL：保留结构与定位信息、按块类型动态打包、注入章节面包屑，产出父子块供下游 small-to-big 消费。纯领域、确定性、零 I/O，是全仓 TDD 主战场。

## Requirements

### Requirement: 解析产物切分为检索单元并落库

系统 SHALL 把 `content_list.json` 切分为检索单元 `Chunk`。切分 MUST 保留每块正文、所属文档与定位信息（原文页码与区域 bbox）以及章节面包屑（Section Path）。同一切分输入 MUST 产出确定性的完全相同输出（幂等、可重放）。切分完成后 SHALL 将 `Chunk` 持久化到 `chunks` 表，可通过归属（`document_id` / `kb_id`）查询。

#### Scenario: 产出带定位与面包屑的块

- **WHEN** 对一份 `content_list.json` 执行切分
- **THEN** 产出多个 `Chunk`，每块含正文、页码、区域坐标可空、章节面包屑、文档归属标识，并落库可查

#### Scenario: 确定性可重放

- **WHEN** 对同一份 `content_list.json` 连续切分两次
- **THEN** 两次产出的 `Chunk` 序列完全一致，顺序、文本、归属、定位均相同

### Requirement: 结构感知切分与按类型档位打包

系统 SHALL 按块类型（`text` / `list` / `table` / `code` / `equation`）采用不同目标长度档位切分，且 MUST 不跨父节点打包：`text`/`list` 按目标 512 token（`table` 1024、`code` 768、`equation` 256）贪心打包，超过上限递归降级（段落→句子→子句）。表格与代码为原子块，MUST NOT 与相邻文本合并。

#### Scenario: 长文本递归降级

- **WHEN** 一段正文超过该类型最大 token 上限
- **THEN** 按句/子句拆分为多个块，保持父节点一致性，不漏字不重复

#### Scenario: 原子块独立成块

- **WHEN** `content_list.json` 中相邻出现代码块与文本
- **THEN** 代码块单独成 chunk，不被前后文本吞并

### Requirement: 表格双表示与代码/公式原文保留

系统 SHALL 对表格产出双表示——一份口语化摘要在检索中可命中、一份 Markdown 原文供生成引用；对代码按函数/类边界切分保留源码；对公式保留 LaTeX 原文。

#### Scenario: 表格双表示

- **WHEN** 切分一个含复杂表格的文档
- **THEN** 产出该表格的口语化摘要 chunk 与 Markdown 原文 chunk，二者均关联同一定位信息

#### Scenario: 公式与代码原文保留

- **WHEN** 切分含公式与代码的文档
- **THEN** 公式 chunk 保留 LaTeX 原文、代码 chunk 保留可编译源码且按函数/类边界切分

### Requirement: 父子块支撑 small-to-big

系统 SHALL 为每个业务块产出 Child chunk 与 Parent chunk。Child chunk 的正文 MUST 含注入的 Section Path 前缀并被标记为可召回（`is_recallable`）；父块 MUST 可经 `parent_id` 关联回其子块，二者均落 MySQL。

#### Scenario: 召回子块、生成用父块

- **WHEN** 切分完成并落库
- **THEN** 部分块被标记 `is_recallable=true`（子块，带面包屑前缀），均关联一个父块；无父子语义的块直接作为自身父块

#### Scenario: 无父子语义扁平块

- **WHEN** 内容本就单块且无层级语境
- **THEN** 该块自身即父块与子块合一，`parent_id` 指向自身或为空且可被检索直接消费