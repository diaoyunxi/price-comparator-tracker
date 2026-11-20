> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「Web 用法」章节拆分而来。

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
