# 实时数据分析与可视化应用平台

支撑实时数据聚合、多维度分析、可视化图表生成和数据应用发布的分析平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8019/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5199/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8019`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 实时聚合器 | `realtime_agg` | 聚合窗口 | 窗口名称、数据源、聚合维度 |
| 事件追踪器 | `event_tracker` | 事件定义 | 事件名称、事件属性、触发条件 |
| 仪表盘构建器 | `dashboard_builder` | 仪表盘 | 仪表盘名称、包含图表、刷新间隔 |
| 查询缓存层 | `query_cache` | 缓存配置 | 配置名称、关联数据集、缓存时长秒数 |
| 分群引擎 | `segment_engine` | 分群定义 | 分群名称、分群条件、所属人口特征 |
| 指标存储 | `metric_store` | 指标快照 | 指标名称、快照值、快照时间 |
| 下钻路径 | `drill_path` | 下钻规则 | 规则名称、起始指标、下钻维度 |
| 分析告警策略 | `alert_policy` | 告警规则 | 规则名称、监控指标、告警条件 |
| 数据报告 | `data_report` | 报告生成器 | 报告名称、包含指标集、报告周期 |
| 异常归因 | `anomaly_analysis` | 归因分析器 | 分析对象、异常时间点、归因维度 |
| 预测模型 | `forecast_model` | 预测任务 | 任务名称、预测指标、预测周期 |
| 分群对比 | `cohort_compare` | 对比报告 | 对比名称、分群A、分群B |
| 分析结果导出 | `data_export` | 导出任务 | 导出名称、查询条件、导出格式 |
| 数据订阅 | `data_subscription` | 订阅任务 | 订阅名称、关联指标、推送条件 |
| 查询历史 | `query_history` | 查询记录 | 查询时间、执行人、涉及数据集 |
| 报告快照 | `report_snapshot` | 快照记录 | 快照名称、所属报告、快照时间 |
| 数据API | `data_api` | 数据接口 | 接口名称、关联指标、请求方式 |
| 留存分析 | `retention_analysis` | 留存任务 | 任务名称、行为事件、留存天数 |
| 漏斗分析器 | `funnel_analyzer` | 漏斗定义 | 漏斗名称、步骤序列、转化窗口小时 |
| 多维数据集构建 | `cube_builder` | Cube定义 | Cube名称、事实表、维度组合 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 报告历史与核数（/report-history）

数据报告除模板配置外，还有“实际生成过的输出”这一层：`report_outputs` 每生成一次就多一条，
同一条输出可能先后补登多条来源凭据。前端入口是 `/report-history`，对应路由
`backend/app/routers/report_history.py`，核心逻辑在 `services/report_history.py`、
`services/report_provenance.py`、`services/report_snapshot.py`。

- **检索**：`GET /api/report-history?business_period=&source=&metric=&as_of=`
  按业务期间、指标取数来源、指标名检索真实输出，每条带该版指标数据。
  来源支持规范名和历史旧简称（`report_sources.aliases`）；旧简称先做全等匹配，
  只有无全等命中才退回包含匹配，避免“北区”把“北区门店”一起带出来。
- **显示名存量**：正文里只有显示名的输出不删除。能解析到规范来源就展示规范名，
  但状态仍是“有待翻查”（`display_only=true`，原文保留在 `display_name`）。
- **凭据**：`POST /api/report-history/{output_id}/attributions` 追加登记，
  可写 `registered_at` 复现历史时点。`status=已确认` 必须带 `evidence_ref`。
  仅显示名的备注（`display_only=true`）不会把已确认来源降级。
- **查验时点**：检索和下发都按 `as_of` / `verify_mode` 还原“那一刻”的来源状态：
  - `filter_time`：固定开始筛选时点，之后补登的凭据不进入本次名单；
  - `dispatch_time`：下发前重新核验，筛选后补登的凭据若已齐全则纳入，并标 `evidence_late`。
- **无凭据不下发**：没有可验证凭据的输出只进“留待下次核数”清单
  （`reconciliation_batch_deferrals`），不会出现在批次名单里。
- **批次冻结**：下发时把名单、来源、凭据、该版指标数据写入
  `reconciliation_batch_items`；之后补登或改确认状态不改写已发批次，
  `GET /api/report-history/batches/{id}` 仍返回当次名单，并可通过 `attribution_trace`
  逐条核对采用过哪条凭据。
- **快照留档**：`POST /api/report-history/snapshots` 必须带 `output_id`
  （结算员选中的那一条输出），不接受跨模板引用；快照固化输出编号、当时来源、
  凭据和该版指标数据。同模板之后补跑新版本不会改写旧快照，
  `GET /api/report-history/snapshots/{id}/verify` 完全从快照自身核对。
- **待继续核对**：检索结果带 `already_dispatched` / `dispatched_batches` /
  `needs_reconciliation`，用来区分已核过的版本和仍需继续核对的版本。

种子场景（`backend/app/seed_report_history.py`，仅 reports 为空时写入）：
报告 41 北区渠道（已确认）、报告 42 同期间旧模板只有简称“北区”（待翻查）、
报告 43 北区门店（不同来源，不应并入渠道检索）。

回归测试：`cd backend && .venv/bin/python tests/test_report_history.py`。

领域：数据工程
子方向：数据分析与数据应用
