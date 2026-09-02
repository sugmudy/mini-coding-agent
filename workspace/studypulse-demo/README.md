# StudyPulse

StudyPulse 是一个学习记录项目。目前已完成 Python 数据层、JSON 持久化、ThreadingHTTPServer 可视化页面与 JSON API。

## 当前结构

- `studypulse/`
  - `models.py`：学习记录数据模型与校验
  - `storage.py`：JSON 持久化与记录存储操作
  - `webapp.py`：HTTP 服务与 API 路由
- `web/`
  - `index.html`：仪表盘页面
  - `styles.css`：蓝紫色响应式样式
  - `app.js`：前端交互逻辑
- `data/records.json`：示例学习记录数据
- `tests/`：pytest 测试

## 已支持的能力

- 列出学习记录
- 新增学习记录
- 按 `id` 切换完成状态
- 按 `id` 删除学习记录
- 科目筛选与统计展示
- 打印 / 保存 PDF

## 运行说明

1. 启动服务：`python -m studypulse.webapp`
2. 打开浏览器访问 `http://127.0.0.1:8000`
3. 如需更换端口，可使用 `python -m studypulse.webapp --port 8080`

## 实现说明

- 数据层对读-改-写操作使用实例级锁，适合 `ThreadingHTTPServer` 并发请求场景
- JSON 落盘采用临时文件 + 原子替换，降低半个文件写入风险
- 删除操作会在 API 和前端中同步刷新统计、筛选与空状态
