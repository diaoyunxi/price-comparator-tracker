> [← 返回文档目录](../README.md)

# 命令行参数（`cli.py`）

| 参数 | 子命令 | 默认 | 说明 |
|---|---|---|---|
| `-V` / `--version` | 全局 | — | 打印版本并退出 |
| `-v` / `--verbose` | 全局 | off | 详细输出 |
| `keyword` | `search` | — | 搜索关键词（位置参数） |
| `--platforms` | `search` | 空 | 平台列表，逗号分隔 |
| `--limit` | `search` | `30` | 每平台条数 |
| `--mock` | `search` | off | 仅用 Mock 数据 |
| `--serial` | `search` | off | 串行采集（调试） |
| `--show` | `search` / `demo` | `10` | 展示前 N 条商品 |
| `--export` | `search` | — | `csv` / `json` |
| `--chart` | `search` | off | 生成图表 |
| `--save-json` | `search` | off | 保存完整结果 JSON |
| `--trend-days` | `search` | `30` | 趋势图天数 |
| `--no-db` | `search` | off | 不写入数据库 |
| `--url-hash` | `trend` | 空 | 按 URL hash 查趋势 |
| `--keyword` | `trend` / `demo` | 空 / `蓝牙耳机` | 按关键词列出商品或演示 |
| `--days` | `trend` | `30` | 趋势天数 |
| `--limit` | `history` | `20` | 历史条数 |

子命令：`search`、`history`、`trend`、`demo`。

> 以上参数均来自 `cli.py::build_parser()` 的 `add_argument` 定义。
