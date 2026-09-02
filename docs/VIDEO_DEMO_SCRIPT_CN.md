# Mini Coding Agent 两分钟最终 Demo 拍摄脚本

## 1. Demo 项目与展示目标

本次不再让模型一轮生成大型看板，而是创建一个更轻量的可视化项目：**StudyPulse 学习打卡仪表盘**。

最终软件具备以下功能：

- 记录学习科目、学习分钟数和完成状态；
- 使用本地 JSON 文件持久化；
- 显示总记录数、累计分钟数、完成率和学习卡片；
- 支持新增记录、切换完成状态和按科目筛选；
- 提供响应式界面和浏览器打印/另存为 PDF；
- Python 领域与存储逻辑有 pytest 自动化测试。

Demo 要证明的不是 StudyPulse 本身有多复杂，而是 Mini Coding Agent 能完成一条可审计的软件工程链路：

```text
空目录
  -> Turn 1：创建数据层与测试
  -> Turn 2：基于已有代码创建 API 和可视化 UI
  -> 浏览器真实交互与 JSON 持久化
  -> Turn 3：根据反馈做增量修复并补回归测试
  -> /history 与 /status
  -> Planner -> Implementer -> Reviewer 完成功能迭代
  -> pytest 通过 + 最终 UI
```

主要展示能力：

- 多轮对话与上下文保持；
- `list_files`、`read_file`、`search_files`、`write_file`、`edit_file`、`run_command`；
- 工作区隔离、安全策略和命令限制；
- 测试驱动的完成判定；
- JSONL 日志、Token、耗时、文件和命令统计；
- 有界、角色隔离的 Multi-Agent 协作。

## 2. 能力边界与讲解口径

- Mini Coding Agent 原生读写 UTF-8 文本文件，不把二进制 PDF 当作普通文本处理。
- StudyPulse 的 PDF 功能由网页的 `window.print()` 和打印样式实现，用户可在浏览器中另存为 PDF；不能讲成 Agent 原生 PDF 解析能力。
- Multi-Agent 是有界串行工作流：Planner -> Implementer -> Reviewer，不是多个写 Agent 并发修改同一目录。
- API 等待片段可以加速或剪短，但测试结果、工具调用和最终页面必须来自一次真实运行。

## 3. 拍摄前准备（不录入最终视频）

### 3.1 终端 A：Agent 环境

不要使用 `conda run` 录制，因为部分 Windows Conda 版本会用 GBK 错误处理 Unicode 输出。

```powershell
conda activate AIenv
cd "C:\Users\14335\Desktop\大三下\南软考核\mini-coding-agent"
. .\.env.local.ps1
$env:AGENT_MODEL="gpt-5.5"
$env:AGENT_REASONING_EFFORT="low"
$env:AGENT_LLM_STREAM="true"
$env:AGENT_LLM_PARALLEL_TOOL_CALLS="false"
$env:AGENT_LLM_TIMEOUT="300"
$env:AGENT_LLM_MAX_RETRIES="1"
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
```

这些设置的目的：

- `low` 降低一次工具决策前的推理等待；
- 流式响应减少长时间无返回；
- 关闭并行工具调用，使 Agent 形成清晰的“决策—执行—观察”循环；
- 最多重试一次，避免网关异常时重复消耗过多额度；
- UTF-8 避免终端输出 `✓` 等字符时报 GBK 错误。

### 3.2 创建空工作区

```powershell
New-Item -ItemType Directory -Force "workspace\studypulse-demo"
Get-ChildItem "workspace\studypulse-demo"
```

`Get-ChildItem` 应无文件输出。重拍时使用新目录，例如：

```powershell
New-Item -ItemType Directory -Force "workspace\studypulse-demo-take2"
```

不要通过递归删除旧素材来准备重拍。

### 3.3 终端 B 与浏览器

终端 B 用于启动生成后的服务；浏览器提前打开空白页，准备访问：

```text
http://127.0.0.1:8000
```

浏览器缩放建议为 90%～100%。隐藏通知、账号信息和无关窗口。

### 3.4 必须先完成一次预演

正式录像前确认：

- 三个 Turn 都能结束；
- `python -m pytest -q` 全部通过；
- `python app.py` 能启动；
- 新增和切换状态后刷新页面，数据仍然存在；
- `/history`、`/status` 正常；
- Multi-Agent 功能迭代最终 approved；
- 日志中没有 API Key；
- 总额度足够完成正式录像。

## 4. 启动持续多轮会话

终端 A：

```powershell
python main.py `
  --workspace "workspace\studypulse-demo" `
  --model gpt-5.5 `
  --reasoning-effort low `
  --safety strict `
  --max-steps 14 `
  --log-dir "logs\studypulse-demo"
```

期望看到版本、模型、workspace、session ID 和 `You>`。

拍摄时讲：

> 这是我从零实现的 Mini Coding Agent。当前进入一个持续多轮会话，模型负责推理和工具选择，文件访问、安全控制、上下文、日志、重试和终止判断都由本地运行时管理。

## 5. Turn 1：只创建数据层和测试

### 单行提示词

```text
请在当前空工作区创建一个名为 StudyPulse 的学习记录项目基础层，本轮只实现 Python 数据层、JSON 持久化和测试，不创建网页或 HTTP 服务。学习记录字段为 id、subject、minutes、completed；subject 去除首尾空格后不能为空，minutes 必须是 1 到 600 的整数，completed 必须是布尔值；存储层支持列出、创建和按 id 切换完成状态，重复设置相同完成状态应保持幂等；数据保存在 data/records.json。保持模块职责清晰，创建 README 记录当前阶段的结构和下一阶段计划，编写 pytest 测试并运行 python -m pytest -q；不要安装依赖、提交或推送代码。
```

### 期望文件

命名允许小幅调整，但结构应接近：

```text
studypulse-demo/
├─ studypulse/
│  ├─ __init__.py
│  ├─ models.py
│  └─ store.py
├─ data/
│  └─ records.json
├─ tests/
│  └─ test_store.py
└─ README.md
```

### 期望工具轨迹

- `list_files` 确认空目录；
- `write_file` 分别创建模型、存储、测试、数据和文档；
- `run_command` 执行 `python -m pytest -q`；
- Turn Report 显示 changed files、测试命令、LLM/tool calls、Token 和耗时。

### 拍摄重点与讲解词

只保留空目录、两个代表性 `write_file`、pytest 通过和 Turn Report。

> 第一轮被刻意限制为一个小目标：先建立可测试的数据层。Agent 从空目录创建领域模型、JSON 存储和测试，并通过真实 pytest 输出证明这一阶段完成。

## 6. Turn 2：在已有数据层上创建可视化 UI

在同一个 `You>` 中输入：

```text
现在基于上一轮已经通过测试的数据层完成 StudyPulse 的可视化版本，不要重写已有领域规则。使用 Python 标准库 ThreadingHTTPServer 提供静态页面和 JSON API；提供查询记录、新增记录和切换完成状态的接口；前端只使用原生 HTML、CSS、JavaScript，显示总记录数、累计学习分钟、完成率、科目筛选和学习记录卡片，并支持新增记录与切换完成状态；准备三条清晰的示例数据；界面使用简洁的蓝紫色仪表盘风格，支持窄屏布局；增加“打印 / 保存 PDF”按钮，使用 window.print() 和 @media print，打印时隐藏表单与操作按钮；更新 README 的运行说明，最后运行 python -m pytest -q，不要在测试中启动长期服务器。
```

### 期望新增文件

```text
studypulse-demo/
├─ app.py
├─ static/
│  ├─ index.html
│  ├─ styles.css
│  └─ app.js
└─ 第一轮已有文件...
```

### 期望工具轨迹

- `list_files` 或 `search_files` 了解上一轮结构；
- `read_file` 读取已有模型和存储接口；
- `write_file` 创建服务端和前端；
- `edit_file` 更新 README 或示例数据；
- `run_command` 再次执行完整测试。

### 拍摄重点与讲解词

保留提示词中“基于上一轮”“不要重写”的部分，以及一次 `read_file`、一次前端文件写入和最终测试。

> 第二轮直接复用上一轮的数据层。Agent 从会话历史知道目标，同时重新读取当前文件获取精确事实，然后增加 API 和可视化页面，没有推翻已经验证的领域逻辑。

## 7. 启动并操作第一版网页

Turn 2 完成后，在终端 B 运行：

```powershell
conda activate AIenv
$env:PYTHONUTF8="1"
cd "C:\Users\14335\Desktop\大三下\南软考核\mini-coding-agent\workspace\studypulse-demo"
python app.py
```

浏览器打开：

```text
http://127.0.0.1:8000
```

快速完成三次操作：

1. 展示统计卡片、科目筛选和三条示例记录；
2. 新增一条“软件工程 / 45 分钟”记录；
3. 将它标记完成并刷新页面，证明 JSON 持久化。

讲解：

> 这不是静态截图。Agent 生成的 Python API、原生前端和 JSON 存储已经真实运行；新增记录、状态切换和刷新后的数据都来自本地服务。

## 8. Turn 3：反馈驱动的增量修复

回到终端 A，在相同会话中输入：

```text
我验收了当前版本，需要做一个小型增量修改：同一科目名称应忽略首尾空格并统一用于筛选，但仍保留用户输入的正常大小写；当 minutes 为布尔值时必须拒绝，因为 Python 的 bool 是 int 的子类；请先搜索并读取相关实现，做最小修改，不要重写整个项目；为这两个边界条件补充 pytest 回归测试，同时在页面空列表时显示友好的空状态，最后运行完整的 python -m pytest -q。
```

### 为什么选择这个反馈

- `bool` 是 `int` 子类，是容易遗漏但很典型的 Python 边界问题；
- 科目规范化涉及领域层、筛选和 UI，能展示跨层定位；
- 空状态是直观可见的小型视觉改进；
- 修改范围小，适合稳定录像。

### 期望工具轨迹

- `search_files` 搜索 `minutes`、`subject` 或筛选逻辑；
- `read_file` 获取精确上下文；
- `edit_file` 最小修改领域逻辑、测试和前端；
- `run_command` 运行完整测试；
- 若第一次失败，Agent 根据真实输出继续修复。

### 拍摄重点与讲解词

保留 `search_files -> read_file -> edit_file -> pytest` 这一完整短链路。

> 第三轮模拟真实验收反馈。Agent 没有重写项目，而是先搜索并读取相关实现，修复 Python 类型边界和筛选一致性，补充回归测试，再由完整测试确认没有破坏已有功能。

## 9. 展示多轮历史和运行时事实

依次输入：

```text
/history
```

```text
/status
```

期望看到：

- 三个用户 Turn；
- completed turns；
- LLM calls 与 tool calls；
- Token 和耗时；
- changed files 与 validation commands；
- JSONL session log 路径。

讲解：

> `/history` 和 `/status` 是本地命令，不会再次调用模型。这里展示的是持续会话中的三轮任务，以及本地运行时根据真实执行累计出的调用、Token、文件、测试和日志。

然后退出：

```text
/exit
```

## 10. Multi-Agent 功能迭代：删除记录与并发安全

退出单 Agent 会话后，在终端 A 运行：

```powershell
$env:AGENT_LLM_MAX_RETRIES="0"
```

这里执行的是一次真实功能迭代，不涉及发布、部署或推送仓库。

```powershell
python main.py --multi-agent `
  --workspace "workspace\studypulse-demo" `
  --model gpt-5.5 `
  --reasoning-effort low `
  --safety strict `
  --max-steps 12 `
  --review-rounds 1 `
  --multi-agent-max-llm-calls 24 `
  --multi-agent-token-budget 40000 `
  --log-dir "logs\studypulse-multi-agent" `
  "对当前 StudyPulse 完成一次有界功能迭代，不涉及发布：新增删除学习记录功能，并提高 ThreadingHTTPServer 场景下 JSON 持久化的并发安全。Planner 先只读检查模型、JsonRecordStore、HTTP 路由、前端和测试，生成包含依赖关系与验收标准的结构化计划；Implementer 实现 JsonRecordStore.delete_record，删除不存在的 id 应明确失败，为读取—修改—写入增加实例级锁，并采用临时文件加原子替换避免写出半个 JSON；新增 DELETE /api/records/{id}，前端增加带确认的删除按钮，删除后统计、筛选和空状态立即刷新，并更新 README；补充删除持久化、缺失 id 和并发创建不会丢记录且 JSON 始终可解析的 pytest 测试。Reviewer 独立检查实现与测试，并必须运行精确命令 python -m pytest -q；保持 Python 标准库后端和零第三方前端依赖，不提交或推送代码。"
```

### 期望阶段

1. `[Planner]` 只读检查存储、API、前端和测试，并输出结构化计划；
2. Coordinator 校验任务 ID、依赖关系和 DAG；
3. `[Implementer]` 根据计划增加删除链路、并发保护、原子写入和测试；
4. `[Reviewer]` 独立读取最终文件，检查功能与并发语义并运行验收命令；
5. 只有 Reviewer approved 且 `python -m pytest -q` 真实成功，最终才显示 `success=true`。

### 拍摄重点与讲解词

保留三个角色名称、Planner 的任务依赖、Implementer 修改存储/API/前端、并发测试和最终 approval；长时间读取与等待加速。

> 最后一部分不是发布，而是一次真实功能迭代。Planner 把删除功能拆分为存储、API、前端和测试任务，Implementer 按依赖实施，Reviewer 独立检查删除语义和并发安全；Coordinator 负责结构化通信、权限、预算和有限审查。

## 11. 最终验证画面

在 StudyPulse workspace 中运行：

```powershell
python -m pytest -q
```

如果 Multi-Agent 修改了文件，重启终端 B 中的服务，然后刷新浏览器。

最终画面必须同时证明：

- pytest 全部通过；
- Multi-Agent `success=true` 或 approved；
- 页面显示统计卡片、筛选和学习记录；
- 新增记录和状态持久化正常；
- 新增记录可以删除，刷新后不会恢复；
- 并发创建测试通过且 JSON 保持可解析；
- 页面有打印/保存 PDF 按钮；
- 日志路径存在。

## 12. 两分钟成片时间轴与逐句讲解

完整运行素材可以很长，最终剪辑控制在 2 分钟。等待部分允许 2～4 倍加速，并标注“等待过程加速”。

### 0:00–0:08 开场与空目录

画面：空 workspace、Agent 启动画面。

> 这是我从零实现的 Mini Coding Agent。我将从空目录分阶段创建一个可运行的学习仪表盘，再通过多轮反馈和多 Agent 完成一次跨层功能迭代。

### 0:08–0:25 Turn 1 数据层

画面：第一条提示词、`list_files`、两个 `write_file`、pytest 和 Turn Report。

> 第一轮只建立领域模型、JSON 存储和测试。Agent 的文件操作和 pytest 都在受限工作区真实执行，完成状态来自运行结果而不是模型声明。

### 0:25–0:43 Turn 2 可视化

画面：第二条提示词、`read_file`、前端写入、测试通过。

> 第二轮复用已验证的数据层。Agent 保留多轮上下文，并重新读取当前代码，再增加标准库 API 和原生可视化页面。

### 0:43–0:58 浏览器交互

画面：统计卡片；新增“软件工程 45 分钟”；标记完成；刷新仍存在。

> 生成结果是实际运行的软件。新增、状态切换和刷新后的数据都经过本地 API 并持久化到 JSON。

### 0:58–1:14 Turn 3 增量修复

画面：`search_files`、`read_file`、`edit_file`、新测试和 pytest。

> 第三轮根据验收反馈定位 Python 类型边界和筛选一致性，做最小修改并补充回归测试，展示真实开发中的反馈恢复能力。

### 1:14–1:24 History 与 Status

画面：`/history` 三个 Turn、`/status` 累计指标。

> 本地命令可以直接查看多轮历史、调用次数、Token、修改文件、验证命令和审计日志，不产生额外模型调用。

### 1:24–1:48 Multi-Agent 功能迭代

画面：Planner 计划、Implementer 修改存储/API/前端、Reviewer 运行并发测试并 approved。

> 最后由三个角色协作增加删除功能和并发安全。它们拥有独立上下文和不同工具权限，本地 Coordinator 控制任务依赖、预算、有限审查和完成条件。

### 1:48–2:00 最终证据

画面：pytest 全通过、Multi-Agent success、网页删除操作和刷新后的结果。

> 只有独立 Reviewer 通过并且验收命令真实成功，系统才报告完成。这展示了工具执行、上下文、安全、观测、多轮对话和多 Agent 协作的完整闭环。

## 13. 剪辑时必须保留与必须隐藏

必须保留：

- 模型、workspace 和 strict safety；
- 三个用户 Turn；
- 六种核心工具各至少出现一次；
- 至少两次 pytest 通过结果；
- 浏览器新增、完成、刷新持久化；
- `/history` 和 `/status`；
- Planner、Implementer、Reviewer；
- Multi-Agent 最终 approval；
- 最终 UI。

可以剪掉：

- 大段代码内容；
- 完整工具 JSON；
- 重复文件读取；
- API 等待；
- 完整 JSONL；
- 无关测试名称。

绝对不能出现：

- API Key 或 `.env.local.ps1` 内容；
- 环境变量完整输出；
- 个人账号、通知或无关窗口；
- 没有解释的失败终端；
- 把浏览器打印说成 Agent 原生 PDF 读写；
- 把串行 Multi-Agent 说成并行写文件。

## 14. 备用处理方案

### 某个 Turn 连接失败

- 不连续重复粘贴同一个大型提示词；
- 退出当前进程，保留日志用于诊断；
- 正式重拍使用新的空 workspace；
- 将失败阶段再拆小，例如 Turn 2 先只创建 `app.py`，下一轮再创建 `static/`；
- 使用预演成功的模型和参数，不在录像当天临时升高 reasoning effort。

### 测试失败

在同一会话追加以下单行提示词：

```text
刚才的测试没有通过，请只根据真实 pytest 输出定位第一个根因，做最小修复后重新运行完整的 python -m pytest -q，不要修改无关功能。
```

保留一次有意义的失败和最终恢复也能体现 Agent 能力，但成片中不要展示长时间盲目重试。

### Turn 2 仍然过长

使用两个更短的备用 Turn，替换原 Turn 2：

```text
基于当前已通过测试的数据层，本轮只创建 app.py 和 JSON API，使用 Python 标准库 ThreadingHTTPServer，实现查询、新增和切换完成状态；不要创建前端；更新 README 并运行 python -m pytest -q。
```

```text
现在只为现有 StudyPulse API 创建 static/index.html、static/styles.css 和 static/app.js，实现统计卡片、科目筛选、新增、切换完成状态、空状态、响应式布局和浏览器打印；不要改写后端领域逻辑，完成后运行 python -m pytest -q。
```

### 浏览器打不开

- 检查终端 B 是否位于 `workspace\studypulse-demo`；
- 查看 README 中的端口；
- 确认旧服务已停止；
- 不要让 Agent 通过 `run_command` 启动长期服务器，因为命令工具有超时保护。

### Reviewer 拒绝

- 如果指出真实问题，允许 Implementer 修复，并把 `--review-rounds` 调为 2；
- 如果只是输出格式错误，使用预演成功的同一配置重拍；
- 不要为了得到 approved 而删除 Reviewer 的验收条件。

## 15. 最终检查清单

- [ ] 使用全新空 workspace；
- [ ] 使用 `gpt-5.5` 和 `--reasoning-effort low` 完成一次预演；
- [ ] 流式开启、并行工具调用关闭；
- [ ] PowerShell UTF-8 配置生效；
- [ ] API Key 未出现在画面和日志；
- [ ] 三个 Turn 全部完成；
- [ ] 六种核心工具均有代表画面；
- [ ] `/history` 和 `/status` 已录制；
- [ ] 浏览器交互和刷新持久化成功；
- [ ] pytest 最终全通过；
- [ ] Multi-Agent 最终 approved；
- [ ] 等待加速有明确标识；
- [ ] 没有夸大 PDF 或并行能力；
- [ ] 最终成片不超过 2 分钟。
