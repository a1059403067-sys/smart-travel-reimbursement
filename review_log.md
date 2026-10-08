# 📋 Review Log — TripFlow 技术审核报告

> 审核人：首席技术审核官（Tech Lead / QA）
> 审核时间：2026-10-08
> 审核范围：提交 `46abfb4`（JWT 鉴权 + auth 接口 REQ-2/3、dashboard 聚合 REQ-1、前端全部页面）+ `f682094`（backend 骨架）对照 `接口契约.md`
> 审核方式：逐字段对照契约；沙箱实测 FastAPI HTTPBearer 行为；静态审查 SQL/密钥/前端三态
> 编号说明：问题编号 R-xx 与 `审核日志.md` 同号（该文件为协作闭环用，A/B 修复后在此更新状态）
> 原则：宁可错杀，不可放过。**结论：整体驳回，7 项 Fail 需修复后重新提交复审。**

---

## 一、契约校验（字段逐项对照）

### [Pass] REQ-2/3 auth 接口 — 字段完全匹配

- `POST /api/auth/login`：请求 `{username, password}` = `LoginRequest` ✅；响应 `access_token/token_type/expires_in/role/user_id/real_name` = `TokenResponse` 与契约逐字段一致 ✅；`expires_in = 1440*60 = 86400` 与契约一致 ✅
- 401/403 文案与契约**逐字一致**："用户名或密码错误" / "账号已被禁用，请联系管理员" ✅
- `GET /api/auth/me`：响应 `{user_id, role, tenant_id}` 与契约一致 ✅；`user_id` 为字符串（str(row.id)）与契约示例 `"1"` 一致 ✅
- 种子账号四角色 `admin/zhangwei/lium/wangcai` 及密码与契约基础信息一致 ✅
- 前端类型 `LoginResponse/Role/UserInfo`（types/index.ts）与契约一致 ✅

### [Pass] REQ-1/4 dashboard / stats — 字段完全匹配

- `summary`（dashboard 4 卡片 + stats 2 卡片）、`department_expense`（name/value/percentage）、`monthly_trend`（month/trips/amount，generate_series 近 6 个月缺月补 0）、`expense_by_type`（中文名映射含"其他"兜底）与契约逐字段一致 ✅
- `?trip_type=entertain` query 参数与契约一致，值走参数绑定 ✅
- 前端 `DashboardData/TravelStats` 类型与契约一致 ✅（`pending_approvals?/month_new_trips?` 前端用 `?? 0` 兜底）

### [Fail] R-05 错误响应语言违反契约（后端 A）

- **问题**：契约明文约定"错误响应统一 `{"detail": "中文提示"}`"，但无 token / Authorization 头格式错误时，`HTTPBearer`（dependencies.py:52）直接抛 **401 `{"detail": "Not authenticated"}`（英文）**。已在 corp_travel_mate 沙箱实测确认（无头与 Basic 头均返回英文 401）。
- **影响**：与契约"401=凭证无效"状态码一致（✅ 不算契约破坏），但 detail 语言违反统一中文约定；前端拦截器 401 分支不展示 detail 所以用户暂不可见，但契约是唯一事实源，接口与文档不一致必须修。
- **修改建议**：在 `get_current_user` 之外统一拦截——给 app 注册 `HTTPBearer` 的自定义异常处理器，或在 `dependencies.py` 中自建 bearer scheme 将 detail 统一为"无效的认证凭证"；并在契约中补充"无 token 返回 401 + 中文 detail"的示例。

### [Fail] R-06 CORS 白名单与契约不符（后端 A）

- **问题**：接口契约.md 声明"CORS 已放行 5173/3001/3000/8080"，但 `main.py:63-67` 白名单中 3001 只有 `http://127.0.0.1:3001`，**缺 `http://localhost:3001`**。前端 dev 端口就是 3001（协作记录.md），用户默认访问 `localhost:3001`。
- **影响**：dev 走 vite 代理（同源）暂不触发；一旦前端配 `VITE_API_BASE_URL=http://localhost:8006` 直连，立即 CORS 失败。契约事实性错误。
- **修改建议**：补 `http://localhost:3001`（以及对称的 127.0.0.1:3000）；或修正契约文案如实描述。

### [Fail] R-07 403 语义链路断裂（前端 B）

- **问题**：`client.ts:33-34` 拦截器对**所有** 403 统一弹"权限不足"，后端中文 detail 被丢弃。登录场景：禁用账号后端返回 403"账号已被禁用，请联系管理员"（契约明文），用户实际看到的是"权限不足"——与契约文案不符，且语义错误。
- **问题 2**：`LoginView.vue:86-90` 注释写"401 是后端明确返回的（用户名/密码不对、账号禁用）"——**账号禁用是 403 不是 401**，注释与后端实现不符。
- **修改建议**：拦截器 403 分支改为 `ElMessage.error(detail ?? '权限不足')`；LoginView catch 补 403 分支（或依赖修正后的拦截器透传文案）；修正注释。

### [Pass] 前端按契约状态对接 — mock 与真实接口划分诚实

- ✅ 已就绪接口（dashboard/stats/auth）前端真实对接；未就绪接口（报销 CRUD、审批）用 mock 且标 `TODO(F13)` 注释——**除 R-02 例外**。

---

## 二、逻辑审查

### 前端 Loading / Error 状态

### [Fail] R-01 P0 级：Dashboard / Analytics 图表首次加载不渲染（前端 B）

- **问题**：`useECharts.ts:10-15` 在 `onMounted` 中 `if (elRef.value) chart = echarts.init(...)`。而 DashboardView.vue:3 / AnalyticsView.vue:11 的图表容器在 `<template v-if="data">` / `v-if="stats"` 内——**首次挂载时 data 为 null，容器 div 不存在 DOM，elRef.value === undefined，chart 保持 null**。数据加载完成后 `setOption` 执行 `chart?.setOption(...)` → **静默 no-op**。全链路无任何重新 init 的钩子 → **三个图表（费用类型饼图/部门饼图/月度趋势）及数据分析页饼图永远空白**。
- **证据链**：`v-if` 挂载时机 → onMounted 一次性执行 → `setOption` 空引用静默失败。vue-tsc 与 vite 启动冒烟**覆盖不到此问题**（无运行时报错），这正是冒烟测试通过的盲区。
- **修改建议**：三选一：(1) `useECharts` 内 `watch(elRef, el => { if (el) chart = echarts.init(el) })`；(2) `setOption` 惰性初始化（chart 为 null 且 elRef 有值则先 init）；(3) 容器 div 常驻 + `v-show` 控制内容。修复后**必须提供浏览器实机截图**作为复测证据（冒烟测试不足以证明）。

### [Fail] R-02 发票解析页对接了未就绪契约（前端 B）

- **问题**：契约 REQ-7 `POST /api/invoice/upload` 状态为 ⏳（等 A-10，未实现）。契约规则明确"⏳ 未实现，**勿对接**"。但 `InvoiceParseView.vue:95` 直接调用 `invoiceApi.upload()`（api/invoice.ts:9）——点击"开始解析"**必然 404**，且拦截器会弹出英文 detail "Not Found"（违反统一中文）。
- **修改建议**：在 A-10 就绪前将 handleParse 切换为本地 mock 占位（与其它未就绪页面同一策略），或在契约变更状态后再放开；同时拦截器对 404 也应显示中文兜底文案。

### [Pass] 其余页面三态处理 — 通过

- ✅ `LoginView`：按钮 loading、401 中文弹窗（detail 透传）、网络错误单独提示（无 response 分支），`finally` 复位 loading
- ✅ `DashboardView`/`AnalyticsView`：数据/`el-empty` 错误态/`v-loading` 三态齐全；`catch` 中清空数据防脏渲染
- ✅ `TravelChatView`：`isStreaming` 禁用输入框与按钮 + 按钮 loading；error 帧弹 `ElMessage.error`；useSSEChat 对 error 帧与非 JSON 行均有兜底
- ✅ `AppLayout.vue:52-59`：`onErrorCaptured` 错误边界 + 更换 key 强制重挂载，与 main.ts errorHandler 注释互相印证
- ✅ 路由导航守卫（router/index.ts:90-104）+ Sidebar 菜单按 role 过滤：前端权限只做 UI 层，后端 `require_role` 为最终防线，设计正确
- ✅ `App.vue`/`main.ts`：全局错误兜底与错误边界分工明确

### 前端 Warn（不阻断但需排期）

- **R-12**（B）：`ReimbursementListView.vue:143`、`ApprovalListView.vue:123` 的 `ElMessageBox.confirm/prompt` 用户点取消时 **reject 未捕获** → unhandled promise rejection（main.ts errorHandler 不捕获 promise 错误）。
- **R-13**（B）：`useSSEChat.ts` 三处隐患：(1) fetch 无超时/无 AbortController，后端挂起时永远 streaming；(2) HTTP 非 2xx 只抛 `HTTP ${status}`，**不读响应体 detail**（中文错误信息丢失）；(3) URL 拼接与 axios 不一致——axios 是 `(VITE_API_BASE_URL ?? '') + '/api'`，fetch 是 `VITE_API_BASE_URL ?? '/api'`，一旦配置 `VITE_API_BASE_URL=http://localhost:8006`，chat 请求打到 `http://localhost:8006/chat` **漏 /api 前缀** 必 404。
- **R-14**（B）：`client.ts:25-31` 任何 401 都静默 logout + 跳登录，**无提示**（session 过期被踢出无感知）；且对 login 请求本身的 401 无豁免（当前恰好无害，逻辑不精细）。另：`authApi.me()` 已定义但全局无调用，登录态只依赖 localStorage，建议 App 启动时调 `/me` 校验。
- **R-15**（B）：`Sidebar.vue:27` 注释"manager/admin"与契约角色 `approver` 不符（仅注释，功能正确）。

### 后端安全审查

### [Fail] R-03 P1 级：自测代码可清空生产库（后端 A）

- **问题**：`analytics.py:274-281` 的 `__main__` 自测块 `TRUNCATE travel_requests, users, departments RESTART IDENTITY CASCADE`，**无环境守卫**。任何人（或 CI 误触）在生产库路径执行 `python -m backend.api.v1.analytics` 即清空三张业务表（含 users——清库后所有账号消失）。
- **修改建议**：自测入口加 `if settings.app_env != "dev": raise SystemExit("仅允许 dev 环境执行自测")`；同规则覆盖 `auth.py:118` 自测块（该块无 TRUNCATE 但会跑 seed，见 R-08）。

### [Fail] R-04 P1 级：数据库弱默认密码（后端 A）

- **问题**：`config.py:48-50` `db_user: str = "postgres"`、`db_password: str = "postgres"` 硬编码弱默认。注释"生产必须改 .env.local"是**纪律而非机制**——`jwt_secret_key`/`deepseek_api_key` 都做了必填校验，db 密码却没有；若生产部署漏配 .env.local，直接以 postgres/postgres 裸奔。
- **修改建议**：与密钥同策略——db_password 移除默认值强制填写；或 `app_env != "dev"` 时校验 `db_password != "postgres"` 否则启动报错。

### [Pass] SQL 注入 / 密钥管理 — 通过

- ✅ SQL 全部参数绑定：`auth.py:76`（`:val`）、`analytics.py:59/187`（`:trip_type`/`:months`）、`seed_data.py`（`$1`）；f-string 拼接的 `where_sql` 仅为固定常量串，无用户输入拼接
- ✅ `.env.local` **未入库**（git ls-files 仅 .env.local.txt 模板）；密钥类配置必填 + 非空校验（config.py:70-75）
- ✅ 密码只存 bcrypt 哈希（seed_data.py 用 `pwd_context.hash`）；登录不区分"用户不存在/密码错误"防账号枚举；bcrypt 校验放线程池不阻塞事件循环
- ✅ `get_current_user` 校验签名与 exp（PyJWT 默认）；`require_role` 返回 403 中文 detail，角色守卫覆盖审批端点（补上了 EduAgent 的坑）
- ✅ 沙箱实测：FastAPI HTTPBearer 无 token 返回 **401**，与 auth.py 自测断言一致（自测断言本身成立）

### 后端 Warn（不阻断但需排期）

- **R-08**（A）：`seed_data.py` 三处：(1) 明文弱种子密码（Admin@123456 等，契约已公开，属已知开发凭据，但）**脚本无 prod 守卫**——生产误跑植入已知弱凭据 admin 账号；(2) `print` 明文密码到 stdout；(3) 建议 app_env=prod 拒绝执行。
- **R-09**（A）：`auth.py:74-81` (1) `username = :val OR email = :val LIMIT 1` **无 ORDER BY**——存在"用户甲 username=X、用户乙 email=X"时登录命中的行不确定；(2) login 无失败次数限速（暴力破解无防护）；(3) JWT 无 issuer/audience 校验（增强项）。
- **R-10**（A）：`main.py:44-45` migrations 失败仅告警不阻断启动——schema 落后时接口 500 且启动无信号。EduAgent 同款设计可接受，但生产建议改为 fail-fast 或至少 ERROR 级告警。
- **R-11**（A）：`analytics.py:85-88` 部门统计用 **INNER JOIN users**——孤儿 user_id 的申请单计入 `summary.total_amount` 但**不进饼图**，饼图合计可能 < 卡片总额。契约未声明口径。建议改 LEFT JOIN 或契约补充口径说明。

---

## 三、审核结论

| 统计 | 数量 |
|---|---|
| Pass 模块 | 6（auth 字段、dashboard/stats 字段、SQL 注入、密钥管理、前端三态、前端类型） |
| Fail | 7（R-01~R-07） |
| Warn | 8（R-08~R-15） |

**裁决：驳回。** 放行条件（阻塞项，必须修复并提供证据后复审）：

1. **R-01（P0）**：前端图表渲染修复 + 浏览器实机截图证据
2. **R-03 / R-04（P1）**：自测清库守卫 + db 密码 prod 校验
3. **R-02 / R-05 / R-06 / R-07**：契约一致性修复（未就绪接口勿对接 / 统一中文 detail / CORS 补 localhost:3001 / 403 文案透传）

Warn 项（R-08~R-15）可随下轮提交一并修复，不阻塞本轮放行，但要求在 `任务看板.md` 中登记排期。

复审入口：修复后在 `任务看板.md` 备注「修复 R-xx」，本审核员按号复核。

---

# 📋 Review Log — 第 2 轮（REQ-8 报销单重构）

> 审核时间：2026-10-08 晚
> 审核范围：工作区未提交改动——backend 新增 `api/v1/reimbursement.py`（REQ-8）、analytics/migrations/router 修改；frontend 新增 `api/reimbursement.ts`、报销单三页重构、mock 删除
> 审核方式：逐字段对照契约 REQ-8 / REQ-1 新增字段；第 1 轮 R-01~R-15 修复情况复核
> **结论：REQ-8 主体实现质量高（状态机/角色守卫/留痕/自测全面），但 3 项契约偏差必须修复（R-16/R-17/R-18）；第 1 轮 15 项问题无一闭环。**

## 一、契约校验

### [Pass] 后端 REQ-8 报销单 CRUD — 主体匹配

- ✅ 状态机与契约一致：draft →(submit) pending step1 →(approver/admin) step2 →(finance/admin) approved；reject 任意审批角色；驳回后重新提交
- ✅ 角色-步骤匹配：approver 审一级、finance 审二级、admin 两级可审；错配 403 中文 detail（reimbursement.py:227-238）
- ✅ 越权与不存在一律 404（不泄露单据存在性）；`to_review` 按 current_step 匹配角色；员工查待审列表 403
- ✅ 响应字段：id/title/status/current_step/total_amount/user_name/department/created_at + 详情 travel_request_title/approvals/reject_reason 与契约一致；留痕 step/action/comment/approver_name/created_at 与契约一致
- ✅ SQL 全部参数绑定；status 筛选先白名单校验；LIMIT/OFFSET 参数化
- ✅ 自测 11 场景覆盖完整状态机 + 权限 + 分页筛选（质量高）
- ✅ dashboard 新增 `reimbursement_status` 五类固定补零（analytics.py），与契约 REQ-1 追加字段逐字一致

### [Fail] R-16 create 状态码与契约不符（后端 A）

- **问题**：reimbursement.py:167 `status_code=status.HTTP_201_CREATED`，契约 REQ-8 写"响应 200"。契约是唯一事实源，二者必须统一。
- **修改建议**：建议契约改为 201（更 RESTful）+ 变更历史记录；或代码改回 200。以契约更新为准，前端 axios 对两者兼容不受影响。

### [Fail] R-17 列表页未使用服务端分页/筛选（前端 B）

- **问题**：契约 REQ-8 明确定义 `page/page_size/status` 且后端已实现；ReimbursementListView.vue:91-93 却一次性拉全量 + 本地过滤分页，注释还写"契约暂无分页参数"——**与契约事实矛盾**，且 `total` 显示的是本地过滤条数。
- **修改建议**：`list({ mine: true, page, page_size, status })` 对接后端分页；删除 TODO 注释；标题筛选若后端未支持（契约确实无 title query）可保留本地或追加契约。

### [Fail] R-18 Dashboard 未对接 reimbursement_status（前端 B）

- **问题**：契约 REQ-1 已新增 `reimbursement_status`（五类补零），后端已实现返回；前端 types/index.ts 的 `DashboardData` 无该字段类型、DashboardView 无第五块渲染。B 在协作记录声明"Dashboard 已对接 REQ-1"——对接不完整。
- **修改建议**：types 补 `reimbursement_status: Array<{name: string; value: number}>`；DashboardView 增加状态分布图（柱状/环形，五类中文标签映射）。

### [Pass] 前端类型与页面 — 主体匹配

- ✅ types Reimbursement/ApprovalRecord/ReimbursementListResponse 与契约一致（status 含 paid、reject_reason 可选、travel_request_title 可空）
- ✅ DetailView `roleMatchesStep` 与契约角色-步骤匹配一致；审批留痕表格字段与契约一致
- ✅ 列表页 pending 状态区分"待审批·经理/财务"（current_step 语义正确）

## 二、逻辑审查

### 前端 Loading / Error

- ✅ List/Detail/Edit 三页 loading（v-loading / acting 按钮态）齐全；错误统一由拦截器弹窗兜底；操作成功后重新 load 刷新
- ✅ EditView 表单校验 + 创建并提交链式调用 + undefined 字段序列化省略（符合契约"可选"）
- ❌ **R-12 未修复且新增 2 处**：ReimbursementListView.vue:148（confirm）、ReimbursementDetailView.vue:145（prompt）的 ElMessageBox 均在 try 外，用户取消 → unhandled rejection
- ⚠️ **R-22**（B）：DetailView `canAct` 只看 status——approver/finance 打开他人 draft 单据可见"提交审批"按钮，点击必 404。应加 owner 判断（需 types 补 user_id，联动 R-19）

### 后端安全与健壮性

- ✅ REQ-8 全部 SQL 参数绑定、角色守卫、越权 404 一致
- ⚠️ **R-20**（A）：approve/submit 先 SELECT 后 UPDATE 无并发保护（TOCTOU）——双 finance 并发 approve step2 会双留痕；approve 与 reject 并发状态竞争。建议 UPDATE 带状态条件检查影响行数，或 SELECT FOR UPDATE
- ⚠️ **R-19**（A）：`_row_to_dict` 返回契约外字段 user_id/travel_request_id/updated_at——契约未声明。契约补充字段说明或代码裁剪（注意前端 owner 判断需要 user_id）
- ⚠️ **R-21**（A）：scripts/init_db.sql 未同步新增 reimbursements/approvals 两表（migrations.py 已加，文件头承诺"同增同改"）——docker 冷启动虽可由 lifespan migrations 兜底，但双 DDL 源已漂移
- ⚠️ **R-23**（B）：EditView 关联差旅申请用手填数字 ID 输入框（REQ-6 未就绪无列表可选，过渡可接受）；建议标注 TODO 待 A-08 后换下拉选择

## 三、第 1 轮问题复核（R-01~R-15）

| 编号 | 状态 | 复核结论 |
|---|---|---|
| R-01 | 🟥 未修复 | useECharts.ts / DashboardView 无改动，**P0 图表不渲染 bug 仍在** |
| R-02 | 🟥 未修复 | InvoiceParseView 仍直连 ⏳ 未就绪接口 |
| R-03 | 🟥 部分修复 | analytics.py 自测不再清 users/departments（注释证实"双会话事故"确已发生）；**但仍 TRUNCATE travel_requests CASCADE（连带清 reimbursements/approvals）且无 env 守卫**；reimbursement.py 自测同款 |
| R-04 | 🟥 未修复 | config.py db 弱默认密码仍在 |
| R-05 | 🟥 未修复 | HTTPBearer 英文 detail 仍在 |
| R-06 | 🟥 未修复 | CORS 白名单仍缺 localhost:3001 |
| R-07 | 🟥 未修复 | 403 文案仍被覆盖为"权限不足" |
| R-08~R-11 | 🟥 未修复 | 后端未改 |
| R-12 | 🟥 恶化 | 新增 2 处同类（见上） |
| R-13~R-15 | 🟥 未修复 | 前端未改 |

## 四、第 2 轮结论

**裁决：REQ-8 功能主体通过，契约偏差驳回。** 放行条件：

1. **R-16**：create 状态码与契约统一（契约改 201 或代码改 200，二选一，契约同步变更历史）
2. **R-17**：列表页对接服务端分页/筛选（后端已就绪，纯前端工作量）
3. **R-18**：Dashboard 对接 reimbursement_status 第五块

第 1 轮遗留的 **R-01（P0）仍是最高优先**：图表渲染 bug 影响所有已对接页面，请 B 优先修复并附实机截图。R-03/R-04（自测守卫/弱默认密码）次之。

⚠️ 提醒 A/B：R-01~R-15 已连续两轮未认领，如持续不处理，第 3 轮将升级所有 🔴 项为阻塞放行条件。
