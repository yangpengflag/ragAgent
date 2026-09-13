## Purpose

提供可运行的前端工程与应用外壳：统一的布局与路由、统一的 API 客户端与错误处理、数据层接线，以及一个能验证前后端联通的系统状态页，作为后续所有业务界面的承载容器。

## ADDED Requirements

### Requirement: 前端工程可本地启动并可构建

系统 SHALL 提供前端工程，支持以单条命令启动开发服务器（默认端口 5173）与生产构建。生产构建 MUST 成功产出静态文件，且类型检查 MUST 无错误。

#### Scenario: 启动开发服务器

- **WHEN** 执行开发启动命令
- **THEN** 服务在 5173 端口可用，访问返回应用 HTML

#### Scenario: 生产构建成功

- **WHEN** 执行构建命令
- **THEN** 构建成功完成并产出静态资源目录

#### Scenario: 类型检查无错误

- **WHEN** 执行类型检查命令
- **THEN** 命令无错误输出

### Requirement: 应用外壳提供统一布局与导航

系统 SHALL 提供固定的应用外壳：侧边栏导航 + 内容区；侧边栏 MUST 在小屏下收起为可打开的抽屉。导航项 MUST 标出当前所在路由。本 change 的导航项为占位项，不承载业务功能。

#### Scenario: 桌面端显示侧边栏

- **WHEN** 在桌面宽度下进入任意页面
- **THEN** 页面呈现侧边栏与内容区两栏结构

#### Scenario: 小屏下导航可收起

- **WHEN** 在移动宽度下进入页面
- **THEN** 侧边栏收起，且存在可打开导航的入口，点击后导航可见

#### Scenario: 当前路由高亮

- **WHEN** 用户位于某个导航项对应的页面
- **THEN** 该导航项呈现选中态，且具有供辅助技术识别的当前项标记

### Requirement: API 客户端统一处理基址、鉴权与错误

系统 SHALL 提供统一的 API 客户端：基址取自 `VITE_API_BASE_URL`（默认 `http://localhost:8000`）；请求 MUST 自动携带 Bearer 访问令牌（若已持有）；当服务端返回 401 时，客户端 MUST 尝试刷新令牌并重放原请求**一次**，刷新失败则跳转登录；所有错误 MUST 归一化为 `ApiError { request_id, error_code, message, details? }` 结构。

字段名 MUST 与后端 JSON 保持一致（snake_case），不得引入大小写转换层。

#### Scenario: 注入访问令牌

- **WHEN** 已持有访问令牌时发起请求
- **THEN** 请求头中包含 `Authorization: Bearer <token>`

#### Scenario: 401 后刷新并重放

- **WHEN** 请求返回 401 且刷新令牌有效
- **THEN** 客户端自动刷新令牌并重放原请求一次，调用方得到重放后的成功结果

#### Scenario: 刷新失败跳转登录

- **WHEN** 请求返回 401 且刷新令牌无效
- **THEN** 客户端跳转登录页，且不重复发起原请求

#### Scenario: 错误归一化

- **WHEN** 服务端返回错误响应
- **THEN** 调用方收到的错误对象包含 `request_id`、`error_code`、`message` 字段，字段名与后端一致

### Requirement: 系统状态页展示后端健康检查结果并覆盖四态

系统 SHALL 提供系统状态页，调用后端 `GET /api/v1/health` 并展示整体状态与 MySQL / Redis / Milvus 三个组件的可用情况。页面 MUST 覆盖四种状态：加载中、有数据、无数据、请求失败；请求失败时 MUST 提供重试入口。

#### Scenario: 加载中

- **WHEN** 页面首次进入且请求未完成
- **THEN** 展示加载占位，不出现空白或错乱布局

#### Scenario: 展示组件状态

- **WHEN** 健康检查返回且三个组件均可用
- **THEN** 页面展示整体状态为 `ok`，并分别列出 MySQL / Redis / Milvus 为可用

#### Scenario: 存在不可用组件

- **WHEN** 健康检查返回且某个组件不可用
- **THEN** 页面整体状态显示为降级，并标出不可用组件及其原因

#### Scenario: 请求失败可重试

- **WHEN** 健康检查请求失败（如后端未启动）
- **THEN** 页面展示错误描述与重试按钮，点击后重新发起请求

### Requirement: 测试与静态检查可一键执行

系统 SHALL 提供测试、lint、类型检查与构建的标准命令，并 MUST 在外壳完成后处于全部通过状态。测试 MUST NOT 依赖真实后端——所有 HTTP 交互由 msw 拦截。

#### Scenario: 运行测试套件

- **WHEN** 后端未启动时执行测试命令
- **THEN** 测试全部通过，输出包含用例统计

#### Scenario: 运行 lint 与类型检查

- **WHEN** 执行 lint 与类型检查命令
- **THEN** 两者均无错误输出

### Requirement: 样式栈遵循项目样式规约

系统 SHALL 使用 Tailwind CSS 4 + shadcn/ui（base-nova / neutral）+ lucide-react，且 MUST NOT 引入其它 UI 组件库（MUI / Chakra / Ant Design 等）或 CSS-in-JS 方案。shadcn/ui 的基础组件 MUST 保持原始形态：MUST NOT 定制样式、MUST NOT 在其中加入业务逻辑。

**允许的例外**：为适配 React 版本差异而补充 `forwardRef` / `displayName`。本项目运行在 React 18，而现行 shadcn/ui 源码按 React 19 的「`ref` 作为普通 prop」语义生成；不作该适配时，Radix 经 Portal / Slot 注入的 ref 会丢失（实测抽屉组件报 `Function components cannot be given refs`，焦点管理随之失效）。

#### Scenario: 未引入其它 UI 库

- **WHEN** 检查工程依赖
- **THEN** 依赖中不包含样式规约禁止的 UI 库

#### Scenario: 图标来源统一

- **WHEN** 界面中使用图标
- **THEN** 图标均来自 lucide-react

#### Scenario: 基础组件仅做版本适配

- **WHEN** 检查 `src/components/ui/` 下的基础组件
- **THEN** 其样式与结构与 shadcn/ui 原始形态一致，仅存在为适配 React 版本所需的 `forwardRef` / `displayName` 差异，且不含业务逻辑
