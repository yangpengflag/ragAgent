# knowledge-base Specification

## Purpose

定义知识库实体与库级授权：知识库是权限与检索的隔离单元，记录其向量化配置；用户通过库级角色获得访问权，且"用户 → 授权知识库集合"必须是检索阶段可查询的真实事实。

## ADDED Requirements

### Requirement: 知识库可创建、查询、更新与软删

系统 SHALL 提供知识库的创建、列表、详情、更新与软删能力。知识库名称 MUST 在**活跃**（未软删）范围内唯一；软删后名称 MUST 可被再次使用。软删 MUST 为标记式删除，不物理删除行。

知识库 MUST 记录其向量化配置（`embedding_model` 与 `embed_dim`），供入库与检索使用；同一向量库 collection 内不得混用不同维度或模型。

#### Scenario: 创建成功

- **WHEN** 以未重名的名称创建知识库并指定向量模型与维度
- **THEN** 返回 201，响应包含 `request_id`、`id`、`name`、`embedding_model`、`embed_dim` 与创建时间

#### Scenario: 名称冲突

- **WHEN** 使用已存在的活跃知识库名称创建
- **THEN** 返回 409 且 `error_code` 为 `conflict`

#### Scenario: 软删后名称可复用

- **WHEN** 某知识库被软删后再以同名创建
- **THEN** 创建成功，不因已软删的同名记录而冲突

#### Scenario: 软删后不可检索

- **WHEN** 知识库被软删
- **THEN** 它不再出现在任何用户的授权集合中，检索结果中不含该库内容

### Requirement: 库级授权以业务数据库为唯一真相源

用户的知识库权限 MUST 以业务数据库中的授权记录为唯一真相源：一个用户在一个知识库 MUST 只持有一个角色（`KB_ADMIN` / `EDITOR` / `VIEWER`）。授权变更 MUST 立即生效；撤销后该用户的检索 MUST NOT 再返回该库内容。

查询授权集合时 MUST 排除已软删的知识库。

#### Scenario: 授予与改角色

- **WHEN** 为某用户授予某库的角色，或把其角色从 `VIEWER` 改为 `EDITOR`
- **THEN** 授权记录反映最新角色，重复授予同一库为覆盖而非新增

#### Scenario: 撤销授权立即生效

- **WHEN** 移除某用户在某库的授权后，该用户发起检索
- **THEN** 该库内容不出现在结果中

#### Scenario: 授权集合排除已软删库

- **WHEN** 用户被授予了某库，但该库随后被软删
- **THEN** 查询该用户授权集合时不包含该库

### Requirement: 知识库管理权限分层

系统 SHALL 区分系统级与库级管理权限：系统级 `ADMIN` MUST 可管理全部知识库及其成员；库级 `KB_ADMIN` MUST 可管理**其被授予 KB_ADMIN 的知识库**及其成员；`EDITOR` 与 `VIEWER` MUST NOT 具有管理权限。无管理权限者调用管理接口 MUST 返回 403 `access_denied`。

#### Scenario: 系统管理员管理任意库

- **WHEN** `ADMIN` 更新或软删任意知识库
- **THEN** 操作成功

#### Scenario: 库级管理员管理本库

- **WHEN** 对某库持有 `KB_ADMIN` 的用户更新该库信息或管理其成员
- **THEN** 操作成功

#### Scenario: 库级管理员不能跨库

- **WHEN** 对 A 库持有 `KB_ADMIN` 的用户试图修改 B 库
- **THEN** 返回 403 且 `error_code` 为 `access_denied`

#### Scenario: 只读成员不能管理

- **WHEN** 对某库仅持 `VIEWER` 的用户调用成员管理接口
- **THEN** 返回 403 且 `error_code` 为 `access_denied`

### Requirement: 提供检索用的授权集合与二次鉴权查询

系统 SHALL 提供按用户查询其全部授权知识库标识的能力，供检索阶段下推过滤使用；并 SHALL 提供"某用户是否可访问指定知识库 / 指定 chunk 集合"的查询能力，供返回引用前二次鉴权使用。查询结果 MUST 来自业务数据库的授权记录（不得来自缓存以外的第三方）。

#### Scenario: 检索阶段拿到真实授权集合

- **WHEN** 检索前查询某用户的授权知识库
- **THEN** 返回其在业务库中的全部有效授权（排除已软删库），可直接作为检索过滤条件

#### Scenario: 二次鉴权可判定越权内容

- **WHEN** 返回引用前用该查询校验某批 chunk 所属知识库
- **THEN** 未授权的库被判定为不可访问，调用方据此阻断
