# 智能差旅报销系统

基于 LLM 意图识别与 LangGraph 多智能体协作的企业差旅管理助手：一句话办理差旅申请（查票、酒店、天气、行程汇总），上传发票自动解析生成报销单，两级审批流转，配套 ECharts 数据可视化看板。

## 核心功能

| 功能 | 说明 | 入口 |
|---|---|---|
| 🤖 统一对话入口 | LLM 意图路由（规则拦截 + DeepSeek 路由，零 token 拦截问候/帮助），SSE 流式输出；支持对话历史持久化 | `/chat` |
| 🚄 差旅申请 | 多智能体协作：信息收集 → 天气查询 → 车票查询 → 酒店推荐 → 行程汇总；缺失信息自动追问；单级审批 | `/travel` |
| 🧾 发票报销 | 上传发票（PDF/JPG/PNG），四层解析管线（类型识别 → 文本提取 → LLM 结构化 → 校验降级）；报销单关联差旅申请，两级审批（部门经理 → 财务） | `/invoice`、`/reimbursements` |
| 📊 数据看板 | 首页四卡片 + 部门费用饼图 + 近 6 个月趋势折线 + 费用类型分布 + 报销单状态分布，ECharts 渲染 | `/dashboard` |
| 👥 角色与权限 | 员工 / 审批人 / 财务 / 管理员四角色，JWT 认证，前后端双重权限控制 | — |
| 📝 自主注册 | 姓名 + 部门 + 密码注册，自动生成拼音 username，无需管理员审批 | `/register` |

**差旅申请 Agent 工作流**（LangGraph）：

```
START → collect_info ─┬─(信息齐全)→ weather → train → hotel → summary → END
                      └─(缺失字段)→ 追问，等待用户补充
```

**发票解析四层管线**：

```
上传（白名单 + 大小校验，落 tempfile，DB 只存路径）
  → ① 类型识别（pymupdf 文本量判断：有文本层 vs 扫描件）
  → ② 文本提取（数字 PDF 直接提取；扫描件 → 转人工核验，PaddleOCR 待 P2）
  → ③ LLM 结构化（Pydantic schema + function calling，失败重试 2 次 + 兜底默认值）
  → ④ 校验层（金额勾稽 |价税合计-(金额+税额)|<0.01、字段格式校验、
        发票号码查重、低置信字段标 needs_human_review）
```

## 系统架构

```
浏览器（Vue 3 + TypeScript + Element Plus + ECharts）
   │ HTTP / SSE（vite dev :3001，或 nginx 静态托管 :3001 反代 /api）
   ▼
FastAPI 后端（:8006）
   ├── 统一对话 unified_chat          ← 意图路由（规则 → LLM → 分发表）
   │     ├─ weather_ticket  查票/天气（直接调用 provider 返回结构化结果）
   │     ├─ travel_apply    → 差旅申请 Agent 群（weather → train → hotel → summary）
   │     ├─ reimbursement   → 引导卡片跳转报销页
   │     ├─ analysis        → 引导卡片跳转看板
   │     └─ chitchat        闲聊
   ├── 差旅申请 API（CRUD / 提交 / 单级审批，留痕 approvals 表）
   ├── 发票 API（上传 → 解析 → 校验降级）
   ├── 报销单 API（CRUD / 提交 / 两级审批：经理 → 财务）
   ├── 统计 API（dashboard 聚合 + stats 子集）
   ├── 认证 API（登录 / 注册 / 部门列表 / 当前用户）
   ├── LLM：DeepSeek（OpenAI 兼容，工厂路由表抽象，可换 Claude/Qwen）
   ├── 外部数据源 providers（train / hotel / map / weather，开发期 Mock 固定数据，
   │        单一函数签名抽象，换第三方 API 不动 Agent 代码）
   └── PostgreSQL 15（:5434 仅回环）：users、departments、travel_requests、
            invoices、reimbursements、approvals、chat_messages
```

**SSE 帧协议**（`POST /api/chat`）：`routing_decision → progress×N → token×N → guidance/meta → done`，异常时 `error` 为终止帧（不再推 done）。

**审批状态机**：

- 差旅申请：`draft → pending → approved / rejected`（单级，审批人或管理员）
- 报销单：`draft → pending(current_step=1 经理) → pending(current_step=2 财务) → approved / rejected → paid`（paid 待 P2）

## 技术栈

**后端**：Python 3.11+、FastAPI、LangChain 1.6 / LangGraph 1.2、SQLAlchemy 2 async + asyncpg、PyJWT + bcrypt + passlib、pymupdf、pypinyin、sse-starlette

**前端**：Vue 3.4、TypeScript 5.4、Vite 5、Element Plus、Pinia、Vue Router、axios、ECharts 5、markdown-it + highlight.js

**部署**：Docker Compose（PostgreSQL 15 + backend + frontend/nginx-unprivileged 三容器）

## 目录结构

```
智能差旅报销系统/
├── backend/
│   ├── main.py                 # 入口（lifespan：迁移 + 日志 + /health）
│   ├── config.py               # pydantic-settings 配置中心（.env.local，密钥必填校验）
│   ├── dependencies.py         # get_db / JWT get_current_user（含 role 鉴权）
│   ├── api/
│   │   ├── router.py           # 路由聚合
│   │   └── v1/                 # auth / unified_chat / travel / invoice / reimbursement / analytics
│   ├── agents/
│   │   ├── travel/             # 差旅申请 Agent（graph/nodes/state/prompts 四文件模板）
│   │   └── reimbursement/      # 发票解析 Agent
│   ├── core/
│   │   ├── router.py           # 意图路由（规则 + LLM，容错降级）
│   │   ├── orchestrator.py     # 编排边界（懒加载、永不抛异常）
│   │   ├── llm_factory.py      # LLM 工厂（路由表 + 限流 + 缓存）
│   │   ├── retry.py            # 三层兜底重试
│   │   └── providers/          # 外部数据源抽象（train/hotel/weather，mock → thirdparty）
│   └── db/migrations.py        # 幂等增量迁移（启动执行）
├── frontend/
│   ├── Dockerfile + nginx.conf # 多阶段构建：node 构建 → nginx-unprivileged 静态 + /api 反代
│   └── src/
│       ├── views/              # 登录/注册/看板/对话/审批中心/发票/报销单/数据分析/系统管理
│       ├── api/                # axios 封装（双拦截器 + 错误边界自愈）
│       ├── composables/        # useSSEChat（SSE 流式）/ useECharts
│       └── stores/             # Pinia（auth）
├── scripts/
│   ├── init_db.sql             # 冷启动建表（PG 容器首启自动执行，幂等）
│   └── seed_data.py            # 种子账号 + 10 人演示数据（幂等，prod 守卫）
├── docker-compose.yml          # 三容器编排（显式项目名 travel-reimburse）
├── .env.example                # 环境变量模板（复制为 .env.local 填写）
├── 架构方案.md                  # 技术落地执行方案（v1.0）
├── 接口契约.md                  # 前后端唯一接口事实源（REQ 编号体系）
└── 任务看板.md                  # 双会话共享任务与进度
```

## 快速开始

### 方式一：Docker 一键部署（推荐）

```bash
# 1. 配置环境变量
cp .env.example .env.local
#    必填：DB_PASSWORD、DEEPSEEK_API_KEY、JWT_SECRET_KEY（DB_USER 可留空走默认 postgres）

# 2. 构建并启动三容器（PG + backend + frontend）
docker compose --env-file .env.local up -d --build

# 3. 灌入种子账号与演示数据（仅本地开发）
docker exec travel_backend python scripts/seed_data.py
```

| 服务 | 容器 | 端口 | 说明 |
|---|---|---|---|
| 前端 | `travel_frontend` | `3001` | nginx 静态托管 + `/api` 反代 backend |
| 后端 | `travel_backend` | `8006` | FastAPI，Swagger 文档 `/docs` |
| PostgreSQL | `travel_pg` | `127.0.0.1:5434` | 仅绑宿主机回环，不暴露局域网 |

> 首次启动 PG 容器自动执行 `scripts/init_db.sql` 建表；后端启动时幂等执行增量迁移。容器内 backend 通过服务名 `postgres` 访问 PG（compose 内已覆盖）。

### 方式二：本地开发

```bash
# 1. 依赖
pip install -r requirements.txt          # 后端（bcrypt 必须 <5，与 passlib 1.7.4 兼容）

# 2. 环境变量（同方式一）
cp .env.example .env.local             # 填 DB_PASSWORD / DEEPSEEK_API_KEY / JWT_SECRET_KEY

# 3. 只起数据库容器（或使用本机已有 PG，改 .env.local 的 DB_* 即可）
docker compose --env-file .env.local up -d postgres

# 4. 种子数据（首次）
python scripts/seed_data.py

# 5. 启动后端（:8006）
uvicorn backend.main:app --host 0.0.0.0 --port 8006 --reload

# 6. 启动前端（:3001，/api 已 proxy 到 8006）
cd frontend && npm install && npm run dev
```

- 后端文档：<http://localhost:8006/docs>（Swagger）
- 前端：<http://localhost:3001>
- 健康检查：<http://localhost:8006/health>

## 角色与种子账号

| 角色 | 账号 | 密码 | 说明 |
|---|---|---|---|
| 管理员 | `admin` | `Admin@123456` | 全权限 |
| 员工 | `zhangwei` | `Employee@123456` | 发起差旅/报销 |
| 审批人 | `lium` | `Approver@123456` | 一级审批（经理） |
| 财务 | `wangcai` | `Finance@123456` | 二级审批（财务） |
| 演示员工 | `demo01` ~ `demo10` | `Demo@123456` | 5 个注册部门各 2 人，含全链路演示数据 |

也可以在登录页自助注册（姓名 + 部门 + 密码，自动生成拼音 username，角色固定为员工）。

## API 概览

统一前缀 `/api`，鉴权 `Authorization: Bearer <JWT>`（有效期 24h）。完整契约（含字段级示例、REQ 编号、变更历史）见 [接口契约.md](接口契约.md)。

| 模块 | 端点 | 说明 |
|---|---|---|
| 认证 | `POST /api/auth/login` | 登录，返回 JWT + role |
| 认证 | `POST /api/auth/register` | 注册（姓名+部门+密码，组合唯一） |
| 认证 | `GET /api/auth/me` | 当前用户 |
| 认证 | `GET /api/departments` | 部门列表（公开，注册下拉） |
| 统一对话 | `POST /api/chat` | SSE 流式，意图路由分发 |
| 统一对话 | `GET /api/chat/history` | 对话历史（limit/before_id 游标翻页） |
| 差旅申请 | `GET /api/travel/requests` | 列表（mine / to_review / 分页筛选） |
| 差旅申请 | `GET /api/travel/requests/{id}` | 详情（含审批留痕） |
| 差旅申请 | `POST /api/travel/requests` | 创建（draft） |
| 差旅申请 | `POST /api/travel/requests/{id}/submit` | 提交审批 |
| 差旅申请 | `POST /api/travel/requests/{id}/approve` / `.../reject` | 审批（approver/admin） |
| 统计 | `GET /api/travel/dashboard` | 看板聚合（卡片+饼图+趋势+类型+报销状态） |
| 统计 | `GET /api/travel/stats` | 统计子集（可选 trip_type 筛选） |
| 发票 | `POST /api/invoice/upload` | 上传解析（multipart，≤10MB；扫描件降级转人工） |
| 报销单 | `GET /api/reimbursements` | 列表（mine / to_review / 状态 / 分页） |
| 报销单 | `GET /api/reimbursements/{id}` | 详情（含关联申请单 + 审批留痕） |
| 报销单 | `POST /api/reimbursements` | 创建（draft） |
| 报销单 | `POST /api/reimbursements/{id}/submit` | 提交（驳回后可重新提交） |
| 报销单 | `POST /api/reimbursements/{id}/approve` | 两级推进（经理 step1 → 财务 step2 → approved） |
| 报销单 | `POST /api/reimbursements/{id}/reject` | 驳回（任意审批角色） |

## 路线图

| 阶段 | 状态 | 内容 |
|---|---|---|
| P0 骨架 | ✅ | compose 部署、JWT 鉴权（含 role）、迁移、种子数据 |
| P1 对话主干 | ✅ | 统一对话意图路由 + 差旅申请 Agent + 审批流 + 报销单 CRUD + 看板 |
| P2 生产化 | ⬜ | PaddleOCR 扫描件识别、invoices 表落库与报销单关联、报销 paid 流程、第三方票务/酒店 API 集成（携程企业版/去哪儿，禁爬虫）、发票真伪查验、系统管理页（用户/部门/报销政策）、ASR 语音输入 |

## 注意事项

- **密钥安全**：`.env.local` 不入 Git；compose 对 `DB_PASSWORD` 启用 `:?` 必填守卫，未配置直接启动失败。
- **外部数据源**：车票/酒店/地图当前为 Mock 固定数据（`TRAIN_PROVIDER=mock` 等），保证流程跑通；生产期切换第三方 API 只需改配置与 provider 实现，Agent 代码不动。
- **bcrypt 版本**：必须 `<5`，5.x 与 passlib 1.7.4 不兼容（72 字节截断行为变更）。
- **端口约定**：PG 宿主 `127.0.0.1:5434`（避开本机 5432 与 EduAgent 5433）、backend `8006`、frontend `3001`。
- **NL2SQL**：架构方案中规划的自然语言查询未实现，当前看板为固定报表接口。
- **开发协作**：接口变更必须同步更新 [接口契约.md](接口契约.md)（唯一事实源），任务进度维护在 [任务看板.md](任务看板.md)。
