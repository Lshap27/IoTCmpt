# 架构升级交接文档

> 分支: `feat/arch-upgrade` | 基础分支: `main` | 日期: 2026-07-08
> **状态更新 (2026-07-08 下午): WF5 Phase C 已提交 (`221302e`),全链路冒烟 + 全部 CI 检查已通过,见「二」。**

## 一、已完成 (7 commits)

| Commit | 内容 | 验证状态 |
|--------|------|---------|
| `8d66a23` | **WF1 工程规范基座**: uv/pyproject.toml, Ruff, mypy, Alembic 迁移, eslint flat config, Prettier, clang-format, pre-commit, 3 条 GitHub Actions | ruff/mypy/pytest 全绿，pre-commit 全绿，pnpm build 通过 |
| `6019f12` | **WF3 MQTT 异步化 + WF2 起点**: paho→aiomqtt, 全局 setter→app.state+Depends, 全部 endpoint 补 response_model, WebSocket 判别联合 WsMessage, export_openapi.py | 29 tests 全绿, openapi.json 导出 9 路径 37 schemas |
| `4bb6ea6` | **WF2 OpenAPI codegen**: @hey-api/openapi-ts 生成 api-client, api.ts 重写为生成 SDK 薄包装, CI codegen drift 检查 | pnpm typecheck/build 通过 |
| `5582da4` | **WF4 TimescaleDB**: images→timescale/timescaledb:2.20.0-pg16, 0002 迁移(hypertable+复合PK), history/bucketed endpoint | Alembic 迁移对 PG 执行成功, hypertable 验证通过, bucketed API 返回正确聚合数据 |
| `cc1e67e` | **WF5 Phase A**: Tailwind v3→v4 (CSS-first @theme inline, 设计 token 零丢失) | pnpm build 通过 |
| `0436d79` | **WF5 Phase B**: shadcn/ui 底座 (Button/Card/Badge/Switch/Tooltip/Skeleton), Panel→Card, AirQualityBadge→Badge, autopilot→Switch | pnpm build 通过 |
| `221302e` | **WF5 Phase C**: TanStack Query + WebSocket 分发器 + hook 拆薄 (providers.tsx, query-keys.ts, ws-dispatcher.ts, use-device-socket.ts, use-device-live 拆薄, page.tsx 改 useQuery) | 见下方「二、验证记录」 |

## 二、验证记录 (2026-07-08, Phase C 提交后全量回归)

- **服务端**: `ruff check` / `ruff format --check` / `mypy app` / `pytest` → 全绿 (29 passed)
- **前端**: `pnpm lint` / `format:check` / `typecheck` / `build` → 全绿 (Next.js 15.5.20, 首页 First Load JS 246 kB)
- **pre-commit** `--all-files` → 8 hooks 全绿
- **Schema drift**: `export_openapi.py` + `pnpm codegen` 后 `git diff --exit-code` → 无 drift
- **全链路冒烟** (docker compose down -v 重建):
  - Alembic 0001→0002 对全新 TimescaleDB 执行成功, `timescaledb_information.hypertables` 确认 telemetry hypertable
  - MQTT 灌 5 条遥测 → `/latest` 返回最新值, `/history/bucketed?bucket=60` 正确聚合 (sample_count=5), `/history` 5 行
  - WebSocket `ws://…/ws/devices/esp32s3-001` 收到 `telemetry` / `event` 判别联合 envelope; 非法 payload (air_quality 枚举外值) 正确回 `error` envelope
  - 浏览器目检 (Playwright + Edge 截图): dashboard 首屏渲染正常; 页面打开期间再灌一条 alert 遥测, 传感卡片/告警徽章/图表/事件流全部实时更新, autopilot 闭环完整触发 (遥测→自动决策触发→AI 分析→决策 envelope, LLM 未配置时降级为「无动作」)

### ⚠️ 冒烟测试注意事项

- **`AIOT_MQTT_ENABLED=true` 必须显式设置** — `Settings.mqtt_enabled` 默认 `False` 且 server/ 下没有 .env, 直接 `python run_dev.py` 时 MQTT 网关不会启动 (且 INFO 日志不可见, 无任何报错)。启动命令: `AIOT_MQTT_ENABLED=true python run_dev.py`
- 冒烟脚本里遥测的 `fusion.air_quality` 只接受 `good | watch | alert | unknown`

## 三、WF5 Phase D — 已完成 (2026-07-08)

> bento grid 布局重构 + 微动效,未新增依赖 (纯 CSS,与仓库既有 keyframe 惯用法一致):
> - `page.tsx` 三个 section 合并为单一 12 列 bento 网格,不等跨度: 指标卡 3×4 / 图表 8 + AI 4 / 相机 3 + 指令 5 + 事件流 4
> - `globals.css` 新增 `.bento-grid`: 子项错峰上浮入场 (nth-child 45ms 步进) + hover 微抬升,`prefers-reduced-motion` 下全部禁用
> - `stat-card.tsx` 补 className 透传
> - 验证: lint/format/typecheck/build 全绿; Playwright 目检 1440px (bento 不等跨度) 与 820px (md 断点 2×2 折叠) 均正常
>
> **至此 WF1–WF5 架构升级计划全部完成。**

## 四、工具版本与环境

| 工具 | 版本 | 备注 |
|------|------|------|
| Python | 3.12 (uv pinned) | `server/.python-version` 锁定, CI Dockerfile 也用 3.12-slim |
| uv | 0.11.27 | `python -m uv` 或 PATH 上的 uv 均可 |
| Node | 24.18.0 | |
| pnpm | 11.7.0 | `corepack pnpm` 或 `~/corepack-bin/pnpm` |
| Docker | 29.6.1 | Windows Desktop |
| ESP-IDF | 5.5.2 | 来自 `firmware/esp32s3/dependencies.lock` |

## 五、架构决策速查

| 决策 | 结论 | 位置 |
|------|------|------|
| DB 不走异步 | 保持同步 SessionLocal, ingest 用 `asyncio.to_thread` 包 | `server/app/main.py:_ingest_sync` |
| 协议单一来源 | openapi.json 入库, `pnpm codegen` 生成前端类型, CI drift 检查 | `server/scripts/export_openapi.py` + `web/openapi-ts.config.ts` |
| WS 类型共享 | schemas.py 定义 WsMessage 判别联合, 通过 export_openapi 脚本注入 openapi.json | `server/app/schemas.py:314` |
| Timescale 卷 | 默认 `docker compose down -v` 重建, 保数据路径见 docker-compose.yml 注释 | `docker-compose.yml` |
| shadcn 桥接 | semantic 变量在 globals.css @theme inline 全量桥接到现有 token (primary=accent, muted=raised) | `web/src/app/globals.css:25-72` |

## 六、关键文件清单

```
C:\Users\lshap\Documents\Code\IoTCmpt\
├── server/
│   ├── pyproject.toml          # uv + Ruff + mypy 配置
│   ├── uv.lock                  # 依赖锁
│   ├── Dockerfile               # uv 两段构建 + alembic upgrade head
│   ├── run_dev.py               # Windows SelectorEventLoop 入口
│   ├── openapi.json             # 导出物 (提交入库)
│   ├── scripts/export_openapi.py
│   ├── alembic/                 # 迁移 (0001 initial, 0002 hypertable)
│   └── app/
│       ├── main.py              # lifespan: MqttGateway start/stop, asyncio.to_thread ingest
│       ├── schemas.py           # Pydantic v2 请求/响应/WS envelope 判别联合
│       ├── api/
│       │   ├── routes.py        # 全 endpoint 带 response_model, app.state Depends 注入
│       │   └── deps.py          # get_mqtt_gateway, get_autopilot, get_autopilot_or_none
│       ├── core/config.py       # pydantic-settings, mqtt_reconnect_seconds
│       └── services/
│           ├── mqtt.py          # aiomqtt MqttGateway (async for + 自动重连)
│           ├── autopilot.py     # maybe_trigger 去 loop 参数, asyncio.create_task
│           ├── analysis.py      # MqttGateway 类型, await publish_json
│           └── telemetry.py     # fetch_history_bucketed (time_bucket)
├── web/
│   ├── components.json          # shadcn/ui 配置
│   ├── openapi-ts.config.ts     # hey-api codegen 输入
│   ├── eslint.config.mjs        # flat config + consistent-type-imports
│   ├── prettier.config.mjs
│   └── src/
│       ├── app/
│       │   ├── globals.css      # Tailwind v4 @import + @theme inline + shadcn 桥接
│       │   ├── layout.tsx       # Providers (QueryClient + Theme)
│       │   ├── page.tsx         # Dashboard (useDeviceLive + useQuery devices)
│       │   └── providers.tsx    # QueryClientProvider + ThemeProvider
│       ├── lib/
│       │   ├── api.ts           # 生成 SDK 薄包装
│       │   ├── api-client/      # @hey-api/openapi-ts 生成物 (提交入库)
│       │   ├── query-keys.ts
│       │   └── ws-dispatcher.ts
│       ├── hooks/
│       │   ├── use-device-live.ts    # 组合层 (useQuery + useMutation + useDeviceSocket)
│       │   └── use-device-socket.ts  # WS 连接管理
│       └── components/
│           ├── ui/              # Button, Card, Badge, Switch, Tabs, Tooltip, Skeleton
│           └── *.tsx             # 业务组件 (ai-panel, command-pad 等已换 shadcn 底座)
├── firmware/esp32s3/
│   ├── .clang-format
│   └── dependencies.lock        # 解除 gitignore 并提交, 钉 ESP-IDF 5.5.2
├── docker-compose.yml           # timescale/timescaledb:2.20.0-pg16, AIOT_AUTO_CREATE_TABLES=false
├── .pre-commit-config.yaml
├── .github/workflows/           # server.yml (含 codegen-drift job), web.yml, firmware.yml
└── HANDOFF.md                   # 本文件
```

## 七、快速验证脚本

```bash
# 服务端全量检查
cd server
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest

# 前端全量检查
cd web
pnpm lint && pnpm format:check && pnpm typecheck && pnpm build

# 全仓 pre-commit
pre-commit run --all-files

# Schema drift
cd server && uv run python scripts/export_openapi.py
cd web && pnpm codegen
git diff --exit-code server/openapi.json web/src/lib/api-client

# 全栈冒烟 (需要 Docker Desktop 运行中)
docker compose down -v
docker compose up -d postgres emqx
sleep 8
cd server && AIOT_DATABASE_URL="postgresql+psycopg://aiot:aiot@127.0.0.1:5432/aiot" uv run alembic upgrade head

# 然后 AIOT_MQTT_ENABLED=true python run_dev.py 起 server (不设该变量 MQTT 网关不会启动!)
# pnpm dev 起 web, 浏览器打开 localhost:3000
# 用下面的 mqtt smoke 脚本灌 5 条遥测, 确认 dashboard 实时刷新 + bucketed API 可用
cd server && uv run python -c "
import json, time, paho.mqtt.client as mqtt
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='smoke')
c.connect('127.0.0.1', 1883)
c.loop_start()
for i in range(5):
    c.publish('devices/esp32s3-001/telemetry', json.dumps({
        'sensors': {'temperature_c': 25+i, 'humidity_percent': 60, 'tvoc_ppb': 100+10*i, 'eco2_ppm': 600},
        'state': {'window_open': False, 'alarm_on': False, 'manual_override': False},
        'fusion': {'air_quality': 'good', 'alarm_enabled': False, 'reason': 'ok'}
    }))
    time.sleep(0.4)
c.loop_stop()
print('done')
"
curl -s "http://127.0.0.1:8000/api/devices/esp32s3-001/latest" | head -c 200
curl -s "http://127.0.0.1:8000/api/devices/esp32s3-001/history/bucketed?bucket=60" | head -c 200
```
