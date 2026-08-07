# GEO 平台正式部署方案

## 结论

当前项目不建议“整个系统只发布到 Vercel”。

原因是系统包含两部分：

- `apps/web`：Next.js 前端，可以正式发布到 Vercel。
- `apps/api`：FastAPI 后端，包含数据库连接、模型 API 调用、定时采集、PDF/Markdown 导出、任务队列等能力，不适合直接依赖 Vercel 前端项目承载。

推荐生产架构：

- 前端：Vercel
- 后端：Render / Railway / Fly.io / 阿里云 ECS / 火山云服务器
- 数据库：Postgres，不能用本地 SQLite
- 定时任务：云服务器 cron、Railway cron、GitHub Actions schedule，或后续接 Celery/队列 worker
- 文件证据：对象存储，例如 S3、R2、OSS、TOS

## Firebase 是否适合

Firebase 可以用，但要分清用途。

适合使用 Firebase 的部分：

- Firebase Authentication：可用于后续替换当前自建登录体系。
- Firebase Hosting：可部署静态前端，但本项目已经更适合用 Vercel 托管 Next.js。
- Cloud Storage for Firebase：可作为截图、PDF、证据文件的对象存储。
- Firestore：可用于轻量配置、通知、状态同步、前端实时状态。

不建议直接用 Firestore 替换主数据库。

当前后端使用 FastAPI + SQLAlchemy，数据模型是关系型的：

- 公司
- 项目
- 目标问题
- 关键词
- 采集任务
- 采集结果
- 答案分析
- 信源引用
- 成熟度报告
- 稿件
- 审核
- 投放
- 用量记录
- 审计日志

这些表之间有大量外键、聚合统计、排序、筛选和报表查询。Firestore 是文档数据库，如果直接替换，需要重写数据访问层、报表统计逻辑和大量接口，不适合作为最快上线方案。

如果想继续用 Firebase 生态，更合适的方案是：

- 前端：Vercel 或 Firebase Hosting
- 后端：Cloud Run / Firebase App Hosting / 其他云服务器
- 数据库：Firebase SQL Connect / Cloud SQL PostgreSQL
- 文件：Cloud Storage for Firebase

最短建议：

- 不选 Firestore 做主库。
- 选 Supabase Postgres、Neon Postgres、Railway Postgres，或 Firebase SQL Connect / Cloud SQL PostgreSQL。
- 后端继续 FastAPI。
- 前端继续 Vercel。

如果目标是长期完全 Firebase 化，需要单独做一次后端数据层重构，把 SQLAlchemy 模型改成 Firestore Collection/Document 结构。这不是 1-2 天的部署工作，而是一次架构迁移。

## Vercel 前端部署

在 Vercel 新建项目时选择：

- Root Directory：`apps/web`
- Framework Preset：Next.js
- Build Command：`pnpm build`
- Install Command：`pnpm install`

环境变量：

```bash
NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
```

其中 `https://api.your-domain.com` 是后端 FastAPI 的正式地址。

当前验证状态：

- `pnpm --dir apps/web exec tsc --noEmit` 通过
- `pnpm --dir apps/web build` 通过

## 后端部署

后端需要独立部署 `apps/api`。

启动命令示例：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

生产环境变量：

```bash
ENVIRONMENT=production
AUTO_CREATE_TABLES=false
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/geo_platform
CORS_ORIGINS=https://your-vercel-domain.vercel.app,https://your-custom-domain.com
AUTH_SECRET=<strong-random-secret>
ARK_API_KEY=<ark-api-key>
OPENAI_API_KEY=
KIMI_API_KEY=
QWEN_API_KEY=
```

注意：

- 当前开发库使用 `apps/api/geo_platform.db`，只适合本地开发。
- 正式上线必须迁移到 Postgres。
- 不要把 API Key 写入前端环境变量。
- `AUTH_SECRET` 必须更换，不能使用 `dev-secret-change-me`。

## 数据库迁移

项目已有 Alembic 配置：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run alembic upgrade head
```

生产建议：

1. 新建 Postgres 数据库。
2. 配置 `DATABASE_URL`。
3. 执行 Alembic 迁移。
4. 创建管理员账号。
5. 配置真实 Provider。
6. 再导入真实项目数据。

## 定时采集与 Worker

GEO 服务依赖“每小时采集”能力。Vercel 前端不能承担这个职责。

可选方案：

- 简单方案：在后端服务器 cron 中运行 `apps/api/scripts/run_due_schedules.py`。
- 云平台方案：Railway/Render 定时任务。
- 工程化方案：接 Celery/RQ/Arq + Redis，把采集任务放入队列。

## 当前不能直接正式发布的缺口

上线前必须完成：

- 后端云部署。
- Postgres 数据库。
- 管理员账号初始化脚本。
- Provider/API Key 生产环境配置。
- CORS 指向 Vercel 域名。
- 定时任务运行环境。
- 文件证据从本地路径改为对象存储路径。
- HTTPS 域名绑定。

## 最短上线顺序

1. 先把后端部署到 Railway 或 Render。
2. 绑定 Postgres。
3. 配置 `ARK_API_KEY`、`AUTH_SECRET`、`CORS_ORIGINS`。
4. 跑迁移并创建管理员。
5. 部署 Vercel 前端，配置 `NEXT_PUBLIC_API_BASE_URL`。
6. 在前端创建正式项目并验证登录、项目页、Provider 测试、真实采集。
7. 再配置定时任务。

## 免费跑起来方案

这套方案目标是“先能在线访问、真实创建项目、真实调用模型”，不是最终生产高可用。

推荐组合：

- 前端：Vercel Hobby 免费额度
- 后端：Render Free Web Service
- 数据库：Supabase Free Postgres
- 定时任务：先手动触发；后续用 GitHub Actions schedule 或升级后端计划
- 文件证据：第一阶段仍保留数据库路径/外链；后续再接 Supabase Storage 或 Cloudflare R2

免费方案限制：

- Render Free 后端无访问时会休眠，首次打开会慢。
- Render 免费后端不适合稳定小时级采集任务，先手动跑真实采集。
- Supabase 免费库适合早期试用，但正式客户变多后需要升级。
- 截图/PDF 等文件证据后续要从本地路径迁到对象存储。

### 1. 创建 Supabase 免费数据库

在 Supabase 创建项目后，复制 Postgres 连接串。

如果 Supabase 给出的连接串类似：

```bash
postgresql://postgres.xxx:PASSWORD@aws-0-region.pooler.supabase.com:6543/postgres
```

在本项目里建议改成 SQLAlchemy/psycopg 格式：

```bash
postgresql+psycopg://postgres.xxx:PASSWORD@aws-0-region.pooler.supabase.com:6543/postgres
```

这个值填到后端环境变量：

```bash
DATABASE_URL=postgresql+psycopg://...
```

### 2. 部署 Render 免费后端

仓库已提供：

- `apps/api/Dockerfile`
- `render.yaml`

在 Render 新建 Blueprint 或 Web Service，选择本仓库。

后端环境变量：

```bash
ENVIRONMENT=production
AUTO_CREATE_TABLES=true
DATABASE_URL=postgresql+psycopg://...
CORS_ORIGINS=https://your-vercel-domain.vercel.app
AUTH_SECRET=<Render 自动生成或手动填写强随机字符串>
ARK_API_KEY=<火山方舟 API Key>
OPENAI_API_KEY=
KIMI_API_KEY=
QWEN_API_KEY=
```

Render 健康检查地址：

```bash
/api/health
```

部署完成后，确认：

```bash
https://your-render-api.onrender.com/api/health
```

返回：

```json
{"status":"ok"}
```

### 3. 初始化云端数据库

后端部署成功后，在 Render Shell 或本地连接云数据库运行：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run alembic upgrade head
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/init_production.py --admin-email your@email.com --admin-password 'your-strong-password'
```

如果暂时不想跑 Alembic，也可以先保留：

```bash
AUTO_CREATE_TABLES=true
```

让 FastAPI 启动时自动建表。正式生产再切回：

```bash
AUTO_CREATE_TABLES=false
```

### 4. 部署 Vercel 前端

Vercel 项目配置：

- Root Directory：`apps/web`
- Framework：Next.js
- Build Command：`pnpm build`
- Install Command：`pnpm install`

前端环境变量：

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-render-api.onrender.com
```

部署后打开：

```bash
https://your-vercel-domain.vercel.app/login
```

使用 `init_production.py` 创建的管理员账号登录。

### 5. 免费方案第一阶段验收

必须验收这些动作：

1. 前端能登录。
2. 能打开项目列表。
3. 能新建公司和项目。
4. 能配置目标问题和关键词。
5. 能看到 Provider 列表。
6. 能对方舟 Provider 做测试调用。
7. 能跑 1 条真实问题采集。
8. 成熟度报告里真实样本数从 0 变成 1。

这 8 项通过，就说明免费方案已经真正跑起来。

## 项目预览

本地预览地址：

```bash
http://127.0.0.1:3000/projects/1
```

如果本地服务没有运行，需要分别启动：

```bash
pnpm run dev:api
pnpm run dev:web
```

当前 Codex 沙盒内端口绑定被限制，可能无法由 Codex 直接启动本地服务；用户本机终端执行上述命令即可打开。
