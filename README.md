# 电商商品价格自动化采集与对比工具

> 按关键词批量采集 **京东 / 淘宝 / 拼多多** 商品信息, 自动清洗去重排序, 提供横向对比、性价比推荐、历史价格趋势图。
> 同时提供 **命令行工具** 与 **FastAPI 演示网页**。

## 目录

- [功能特性](#功能特性)
- [整体架构](#整体架构)
- [快速开始](#快速开始)
- [命令行用法](#命令行用法)
- [Web 用法](#web-用法)
- [反爬策略](#反爬策略)
- [数据获取核心逻辑](#数据获取核心逻辑)
- [数据可视化方案](#数据可视化方案)
- [配置参考](#配置参考)
- [目录结构](#目录结构)
- [开发与测试](#开发与测试)
- [法律与合规](#法律与合规)

---

## 功能特性

- **多平台批量采集**: 京东、淘宝、拼多多, 每平台默认 30 条
- **标准化数据**: 统一字段 (标题/价格/销量/店铺/评分/链接/SKU)
- **自动清洗去重**: 价格解析、销量单位统一 (1.2万→12000)、店铺评分归一化、按价格升序
- **横向对比**: 平台均价/最低/最高/中位价/均销量/均评分
- **性价比推荐**: 加权综合分 (价格 0.45 + 销量 0.30 + 评分 0.25), Top N 推荐
- **价格趋势**: SQLite 历史快照, 多次采集后查看趋势
- **可视化**:
  - CLI: matplotlib 箱线图、分布图、均价对比、趋势折线
  - Web: ECharts 互动图表
- **反爬策略**: 随机 UA + 间隔抖动 + 重试退避 + Referer 伪装 + 代理池 + Cookie 池 + Playwright 降级 + 验证码识别 hook
- **Mock 回退**: 真实爬虫失败时自动回退高质量 Mock 数据, 保证演示始终可用
- **跨平台**: Linux / macOS / Windows 全适配

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户入口                              │
│   ┌──────────────────┐         ┌──────────────────────┐     │
│   │  CLI (cli.py)    │         │  Web (main.py)       │     │
│   │  argparse + rich │         │  FastAPI + Jinja2    │     │
│   └────────┬─────────┘         └──────────┬───────────┘     │
│            │                              │                  │
└────────────┼──────────────────────────────┼─────────────────┘
             │                              │
             ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  编排层 (core/runner.py)                     │
│   run_crawl(): 多平台并行调度 → 合并 → 清洗 → 入库 → 推荐    │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│   爬虫层 (scrapers/)      │    │  清洗对比层 (core/)       │
│  ┌─────────────────────┐  │    │  ┌────────────────────┐  │
│  │ BaseScraper        │  │    │  │ dedup.py  清洗去重  │  │
│  │  ├─ JDScraper      │  │    │  │ compare.py 推荐    │  │
│  │  ├─ TaobaoScraper  │  │    │  │ models.py 数据模型 │  │
│  │  ├─ PddScraper     │  │    │  └────────────────────┘  │
│  │  └─ MockScraper    │  │    └──────────────────────────┘
│  └─────────────────────┘  │
│   ↓ (失败回退)            │    ┌──────────────────────────┐
│  AntiCrawlSession:        │    │  存储层 (core/database)  │
│  - UA 池                  │    │  SQLite (history.sqlite3)│
│  - 代理池 / Cookie 池     │    │  - products 表           │
│  - 重试退避               │    │  - crawl_meta 表         │
│  - Playwright 降级        │    └──────────────────────────┘
│  - 验证码 hook            │
└──────────────────────────┘    ┌──────────────────────────┐
                                │  可视化 (viz/charts.py)   │
                                │  matplotlib: 箱线/分布/  │
                                │  均价/趋势               │
                                └──────────────────────────┘
```

### 关键设计点

1. **接口抽象**: `BaseScraper` 定义统一接口, 子类只需实现 `_do_search()` 与 `parse()`, 新增平台仅需新增一个文件
2. **编排解耦**: `runner.py` 编排多平台采集, CLI 与 Web 共用同一编排逻辑, 行为一致
3. **数据契约**: 所有爬虫最终都产出 `Product` 列表, 下游清洗/对比/可视化输入稳定
4. **失败回退**: 真实爬虫 → Mock 数据, 保证演示可用 (Mock 数据有真实词库与合理分布)
5. **历史快照**: 每次采集写入 SQLite, 支持多日趋势; URL hash 作为商品稳定标识
6. **配置外置**: `config.py` + `config.local.yaml` 覆盖, 敏感信息 (Cookie/代理) 不入库

---

## 快速开始

### 环境要求

- Python **3.8+**
- pip
- (可选) Playwright + Chromium: `playwright install chromium` (重度反爬降级用)

### 一键安装

```bash
cd price-comparator-tracker
python install.py
```

`install.py` 会自动: 检查 Python 版本 → 创建目录 → 安装依赖 → 生成示例数据 → 检查更新 → 验证导入 → 打印使用指引。

### 手动安装

```bash
pip install -r requirements.txt
python tools/gen_sample.py    # 生成示例数据
```

---

## 命令行用法

### 标准采集

```bash
# 关键词采集 (默认 3 平台各 30 条, 真实爬虫 + Mock 回退)
python cli.py search 蓝牙耳机

# 指定平台与数量
python cli.py search 机械键盘 --platforms jd,pdd --limit 20

# 导出 CSV + 生成图表
python cli.py search 蓝牙耳机 --export csv --chart

# 保存完整结果 JSON
python cli.py search 蓝牙耳机 --save-json

# 仅 Mock 数据 (快速演示, 不发起真实请求)
python cli.py search 蓝牙耳机 --mock

# 串行模式 (调试)
python cli.py search 蓝牙耳机 --serial --verbose
```

### 历史与趋势

```bash
# 列出最近采集关键词
python cli.py history

# 查看某商品价格趋势
python cli.py trend --url-hash <hash> --days 30
```

### 快速演示

```bash
python cli.py demo
# 等价于: search 蓝牙耳机 --mock --chart
```

### 输出示例

```
== 采集摘要 ==
平台       采集数  Mock回退  耗时(s)  错误
jd         30      是        0.12    real_crawl_exc:ConnectionError
taobao     30      是        0.08    real_crawl_empty
pdd        30      是        0.10    captcha_triggered

清洗: 输入 90 -> 输出 90 (无效价格 0, 重复 0)

== 商品横向对比 (按价格升序, 共 90 条, 显示前 10) ==
平台  商品标题                       价格      销量      店铺       评分
拼多多 魅族 蓝牙耳机 T 定制版...    ¥69.00    94,500   魅族数码专营 4.5
淘宝  绿联 蓝牙耳机 二代 12+256...   ¥79.00    56,800   绿联旗舰店  4.7
...

== 平台统计对比 ==
平台   条数  均价      最低     最高      中位价    均销量    均评分
京东   30    ¥415.67   ¥89.00  ¥1599.00  ¥159.00   19,650   4.78
淘宝   30    ¥654.00   ¥79.00  ¥1299.00  ¥249.00   22,150   4.83
拼多多 30    ¥160.67   ¥69.00  ¥289.00   ¥154.00   54,000   4.67

价差分析:
  最便宜: [拼多多] 魅族 蓝牙耳机 T...  ¥69.00
  最贵:   [京东]   苹果 蓝牙耳机 Max... ¥1599.00
  价差:   ¥1530.00 (2217.4%)

== 性价比推荐 Top N ==
排名  平台   商品            价格      销量      综合分  推荐理由
#1   拼多多 魅族 蓝牙耳机... ¥69.00   94,500   87.5    价格处于低位 / 销量领先
#2   拼多多 realme 蓝牙耳机 ¥99.00   67,800   72.1    价格处于低位 / 销量领先
...

总耗时: 8.34s
```

---

## Web 用法

### 启动

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8765 --reload
```

访问 http://localhost:8765

### 页面交互

1. **初始展示**: 页面加载后立即显示 `sample_products.json` → `sample_result.json` 的示例数据 (18 条商品)
2. **现场采集**: 在输入框输入关键词, 选择平台与数量, 点击「开始采集」
   - 默认走真实爬虫 (失败回退 Mock)
   - 勾选「仅模拟数据」直接走 Mock (快速演示)
3. **进度反馈**: 实时显示任务状态与进度条 (pending → running → success)
4. **结果展示**:
   - 统计卡片 (总数 / 最便宜 / 最贵 / 价差比)
   - 平台对比表
   - 4 张 ECharts 图表 (均价对比 / 价格分布 / 箱线图 / 推荐得分)
   - 商品列表 (按价格升序, 含推荐徽章)
5. **价格趋势**: 点击商品列表行, 加载该商品 30 天价格趋势折线图

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/api/sample` | 获取初始示例数据 |
| POST | `/api/crawl` | 启动采集任务, 返回 `task_id` |
| GET | `/api/task/{task_id}` | 查询任务状态与结果 |
| GET | `/api/history` | 历史关键词列表 |
| GET | `/api/trend?url_hash=...&days=30` | 单商品价格趋势 |
| GET | `/api/trend/keyword?keyword=...&days=30` | 关键词下所有商品趋势 |
| GET | `/api/health` | 健康检查 |
| GET | `/docs` | Swagger UI |

---

## 反爬策略

本工具实现 **重度反爬**, 集成于 `core/anti_crawl.py`:

| 策略 | 实现 | 说明 |
|------|------|------|
| 随机 User-Agent | `USER_AGENTS` 池 50+ | 含桌面/移动/京东/淘宝/拼多多 App UA |
| 请求间隔抖动 | `random_delay()` | 2-5s + 0-0.8s 抖动 |
| 失败重试 | `max_retries=3` | urllib3 级 + 应用级双重 |
| 指数退避 | `_backoff()` | 1.5 * 2^n, 上限 30s |
| Referer/Origin 伪装 | `default_headers()` | 各平台对应域名 |
| 代理池 | `ProxyPool` | 文件加载, 轮询, 失败剔除 |
| Cookie 池 | `CookiePool` | `cookies/<platform>.txt` |
| Playwright 降级 | `_playwright_fallback()` | requests 失败时启用 headless 浏览器, 含反检测脚本 |
| 验证码识别 hook | `captcha_solver` | 留接口, 默认不实现, 可注入 |
| Session 复用 | `requests.Session` | TCP 连接复用 |

### 反爬启用方式

```python
# config.local.yaml (创建后自动覆盖默认值)
crawl:
  enable_proxy_pool: true
  enable_cookie_pool: true
  enable_playwright_fallback: true
  max_retries: 5
  request_delay_min: 3.0
  request_delay_max: 7.0
```

### 代理池文件

`proxy_pool.txt` (每行一个):

```
http://1.2.3.4:8080
http://5.6.7.8:3128
```

### Cookie 文件

`cookies/jd.txt`:

```
pt_key=xxx; pt_pin=xxx; ...
```

---

## 数据获取核心逻辑

### 流程

1. **请求构造**: 根据平台选择对应 UA / Referer / Cookie
2. **优先移动端 H5**: 反爬强度低于 PC 端, 多数无需登录可获取列表
3. **多策略解析**:
   - 京东: 移动端 `so.m.jd.com` → PC `search.jd.com` → 内嵌 JSON (`glb` 变量)
   - 淘宝: 移动端 `s.m.taobao.com` → 内嵌 JSON (`g_page_config` / `__INITIAL_STATE__`)
   - 拼多多: 移动端 `mobile.yangkeduo.com` → API `/proxy/api/api/goods/v2/search`
4. **BeautifulSoup 解析**: 多套 CSS 选择器兼容, 容错单条失败
5. **字段标准化**: `parse_price()` / `parse_sales()` / `parse_rating()` 统一异构格式
6. **失败回退**: 任一阶段失败 → `MockScraper` 生成同结构数据

### 字段标准化示例

| 原始 | 标准化 |
|------|--------|
| `¥99.50` | `99.50` |
| `1.2万+` | `12000` |
| `已拼1.2万件` | `12000` |
| `96%` (店铺分) | `4.80` (5分制) |
| `4.8分` | `4.80` |

### 性价比综合分公式

```
综合得分 = 价格归一化(越低越好) * 0.45
        + 销量归一化(越高越好) * 0.30
        + 店铺评分归一化 * 0.25

归一化: (x - min) / (max - min)  →  [0, 1]
```

---

## 数据可视化方案

### CLI (matplotlib, `viz/charts.py`)

| 图表 | 类型 | 用途 |
|------|------|------|
| 平台价格箱线图 | boxplot | 各平台价格分布与离散度 |
| 商品价格分布 | histogram | 价格区间商品数量分布, 渐变色 |
| 平台均价对比 | bar | 最低/均价/最高对比, 数值标注 |
| 价格趋势 | line | 单商品近 N 天价格, 极值标注 |

输出: PNG, 保存到 `exports/` 目录, 120 DPI。

### Web (ECharts 5.5, 前端 `web/templates/index.html`)

| 图表 | 类型 | 交互 |
|------|------|------|
| 平台价格区间 | bar (3 系列) | 鼠标悬停 tooltip |
| 价格分布柱状图 | bar (渐变) | 自动分桶 15 个区间 |
| 平台箱线图 | boxplot | 5 数概括 |
| 性价比推荐得分 | bar (横向) | 排名 + 得分标注 |
| 价格趋势折线 | line + area + markPoint | 含最低/最高标记 |

中文字体: 桌面端默认调用系统字体, CSS 已声明 `PingFang SC / Microsoft YaHei / Noto Sans CJK`。

---

## 配置参考

### 默认配置 (`config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `crawl.limit_per_platform` | 30 | 每平台采集条数 |
| `crawl.request_delay_min/max` | 2.0 / 5.0 | 请求间隔 (秒) |
| `crawl.max_retries` | 3 | 失败重试次数 |
| `crawl.request_timeout` | 15 | 请求超时 (秒) |
| `crawl.enable_proxy_pool` | false | 启用代理池 |
| `crawl.enable_playwright_fallback` | true | 启用 Playwright 降级 |
| `crawl.fallback_to_mock` | true | 真实失败回退 Mock |
| `crawl.real_crawl_timeout` | 60 | 真实爬虫总超时 (秒) |
| `web.host` | 0.0.0.0 | Web 监听地址 |
| `web.port` | 8765 | Web 端口 |
| `web.max_concurrent_tasks` | 3 | 后台任务并发上限 |
| `recommend_top_n` | 5 | 性价比推荐数 |

### 自定义配置

创建 `config.local.yaml` (已 gitignore):

```yaml
crawl:
  limit_per_platform: 50
  enable_proxy_pool: true
  request_delay_min: 3.0
  request_delay_max: 7.0
web:
  port: 9000
recommend_top_n: 10
```

---

## 目录结构

```
price-comparator-tracker/
├── README.md                  # 本文档
├── VERSION                    # 版本号
├── requirements.txt           # 依赖
├── .gitignore
├── config.py                  # 全局配置
├── install.py                 # 一键安装
├── updater.py                 # 自动更新检查
├── cli.py                     # CLI 入口
├── main.py                    # FastAPI Web 入口
├── core/
│   ├── __init__.py
│   ├── models.py              # 数据模型 (Product / CrawlResult)
│   ├── database.py            # SQLite 历史存储
│   ├── dedup.py               # 清洗去重 + 字段标准化
│   ├── compare.py             # 横向对比 + 性价比推荐
│   ├── anti_crawl.py          # 反爬策略 (重度)
│   └── runner.py              # 采集编排器
├── scrapers/
│   ├── __init__.py
│   ├── base.py               # 爬虫基类
│   ├── jd.py                 # 京东爬虫
│   ├── taobao.py             # 淘宝爬虫
│   ├── pdd.py                # 拼多多爬虫
│   └── mock.py               # Mock 数据生成
├── viz/
│   ├── __init__.py
│   └── charts.py             # matplotlib 图表
├── web/
│   ├── __init__.py
│   ├── static/
│   │   └── style.css
│   └── templates/
│       └── index.html         # 主页面 (含 ECharts)
├── tools/
│   └── gen_sample.py         # 示例数据生成
├── data/
│   ├── sample_products.json  # 原始示例数据
│   └── sample_result.json    # 清洗后示例结果
├── exports/                  # CLI 导出目录 (运行时生成)
├── logs/                     # 日志目录 (运行时生成)
└── data/runtime/
    └── history.sqlite3       # SQLite 数据库 (运行时生成)
```

---

## 开发与测试

### 重新生成示例数据

```bash
python tools/gen_sample.py
```

### 验证模块导入

```bash
python -c "from core.runner import run_crawl; print('OK')"
```

### 单元测试 (Mock 路径)

```bash
python cli.py demo --verbose
```

### 添加新平台

1. 在 `scrapers/` 新建 `xxx.py`, 继承 `BaseScraper`
2. 实现 `platform` / `_do_search()` / `parse()`
3. 在 `scrapers/__init__.py` 的 `get_scraper()` 注册
4. 在 `config.py` 的 `platforms` 添加中文名

### 自动更新

启动时 `install.py` 会自动检查 GitHub release 是否有新版本, 仅提示不自动下载执行 (避免供应链风险)。

```bash
# 手动检查更新
python updater.py
```

如需在应用启动时自动检查, 在 `main.py` / `cli.py` 启动流程中调用 `updater.check_for_updates(silent=True)`。

---

## 法律与合规

⚠️ **重要提示**

- 本工具仅作 **技术学习与研究** 用途, 不用于商业爬取
- 京东/淘宝/拼多多的服务条款通常禁止自动化访问, 真实爬虫可能违反 ToS
- 默认配置下, 真实爬虫失败自动回退 Mock 数据, 不强制突破反爬
- 使用本工具产生的一切后果由使用者自行承担
- 建议优先使用各平台官方开放 API (需申请资质)
- 请遵守 `robots.txt` 与目标站点的访问频率限制

---

## 版本

当前版本见 `VERSION` 文件。

## License

MIT
