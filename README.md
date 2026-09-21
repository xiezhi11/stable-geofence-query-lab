# Deterministic Geofence Event Service

服务把携带事件时间和经纬度的事件匹配到当时有效的围栏，并保证批量、窗口、分页、重启和测试结果都可复现。

## 核心语义

- 边界统一算命中：圆形包含圆周，多边形包含边和顶点。
- 多个区域重叠时按 `priority` 降序、区域 `version` 降序、区域 ID 降序决胜。
- 匹配只使用事件携带的 `timestamp`，不使用服务器当前时间。
- 每次 `PUT /zones` 原子替换整套区域并生成新的目录版本；校验失败不会保留半套边界。
- 正在处理的批次固定使用批次开始时拿到的版本快照。
- 被撤销的区域不会匹配新事件，但历史记录仍保留原区域与确认状态。
- 重复 `event_id` 返回第一次存储的匹配、确认时间和明确的 `duplicate_event` 错误对象。
- 时间窗口支持跨日范围和迟到事件；超过 `late_until` 后记录为 `closed/window_closed`。
- 所有内部时间以 UTC 存储；重启或修改进程时区不会改变已确认结果。
- 分页按 `(timestamp,event_id)` 稳定排序，游标不受后续插入影响。

## 持久化与固定时钟

设置 `GEOFENCE_STATE_PATH` 后启用持久化。`.json` 使用 JSON 文件，`.db` 或 `.sqlite` 使用 SQLite；两者都通过同一个 `StateStore` 协议替换。

请求头 `X-Fixed-Clock` 只在当前请求内固定时钟，适合重放迟到事件。`POST /admin/clock` 可全局设置测试时钟，`POST /admin/reset` 会清空区域、窗口、事件和时钟。

## API

`PUT /zones` 原子更新区域：

```json
{"zones":[{"id":"z1","name":"Zone","version":1,"priority":10,
"effective_from":"2026-01-01T00:00:00Z","effective_to":null,
"shape":{"type":"circle","center":[10.0,20.0],"radius_m":100}}]}
```

`POST /windows` 创建窗口：

```json
{"id":"daily","start":"2026-01-01T20:00:00Z",
"end":"2026-01-02T02:00:00Z","late_until":"2026-01-02T03:00:00Z"}
```

`POST /events` 提交单事件；`POST /events/batch` 批量提交。批量返回项严格保持输入下标和顺序，单项失败不影响其他合法项。

`GET /matches` 查询记录，支持 `zone_id`、`status`、`unmatched_only`、`limit`、`cursor`。响应中的 `total`、页内记录和 `next_cursor` 使用同一筛选条件。

## 稳定错误对象

错误均返回：

```json
{"error":{"code":"invalid_coordinates","message":"...","field_path":"latitude"}}
```

稳定代码包括 `invalid_format`、`invalid_coordinates`、`invalid_cursor`、`zone_not_found`、`window_not_found`、`version_expired`、`duplicate_event`。批量字段路径形如 `events[1].latitude`，响应不包含内部路径或堆栈。

## 本地运行

```bash
python3 -m pip install -r requirements.txt
GEOFENCE_STATE_PATH=./tmp/geofence.sqlite python3 -m uvicorn main:app --reload
```

## 测试与报告

```bash
python3 -m pytest
```

测试使用独立的内存服务、固定时钟、可替换通知器以及 JSON/SQLite 数据库夹具；每个样例后自动重置。运行后生成：

- `test-reports/cases.json`：每个样例的输入版本、时钟值、清理结果和污染来源。
- `test-reports/cases.md`：便于直接查看的报告。

单个失败样例可直接用节点 ID 重放：

```bash
python3 -m pytest tests/test_geofence.py::test_boundary_circle_and_polygon_are_included
```
