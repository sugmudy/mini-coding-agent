# 软件工程设计与演进说明

本文记录 V4.1 优化中采用的软件工程原则、历史数据模型、并发边界和一致性取舍。目标不是堆叠概念，而是让每一项设计都能对应到代码中的不变量、故障模式和自动化测试。

## 1. 质量属性与优先级

本项目按以下顺序权衡质量属性：

1. **正确性与可恢复性**：失败不能被误报为成功，文件不能出现半写入状态。
2. **安全性**：执行权限采用最小权限和 fail-closed 原则。
3. **可理解性**：核心控制流由本地、显式、可测试的代码完成。
4. **可观测性**：模型叙述与运行时事实分离，问题可通过状态和事件追踪复盘。
5. **可演进性**：当前单 Agent 的边界要能自然扩展为后续 Coordinator + Workers，而不是提前引入难以验证的共享并发。

## 2. 模块化与职责分离

项目采用“高内聚、低耦合”的分层设计：

- `Agent` 只负责编排会话状态机和 model/tool 循环；
- `ContextManager` 只负责从完整历史构建有界且协议合法的模型视图；
- `ToolRegistry` 负责 Schema 与调用分派，具体能力由 File/Search/Shell 工具实现；
- `SafetyPolicy` 只产生风险决策，UI 通过回调完成审批，低层代码不直接依赖终端；
- `AgentState`/`TurnState` 保存运行时事实，UI 仅做展示；
- `SessionLogger` 保存审计事件，不参与业务决策。

这体现了单一职责原则和依赖倒置思想：安全策略依赖抽象的审批回调，而不是依赖某个具体 UI；Agent 依赖工具注册表接口，而不是在循环中硬编码每种工具。

## 3. 会话状态机与不变量

一个 Agent 的生命周期为：

```text
NEW -> SESSION_ACTIVE -> TURN_RUNNING -> SESSION_ACTIVE -> SESSION_FINISHED
                           |  success/error  |
                           +-----------------+
```

关键不变量：

- 一个 Agent 同时最多有一个 `TURN_RUNNING`；并发调用 `run_turn()` 会 fail-fast，而不是等待后交错执行。
- 每个 assistant tool call 后只追加具有相同 `tool_call_id` 的 tool result；上下文压缩以完整交互块为单位。
- 每个 Turn 只能结束一次，状态为 `complete` 或 `error`。
- 修改文件后，验证提醒只检查当前 Turn 的成功命令，不能复用旧 Turn 的验证结果。
- 会话结束时不得存在运行中的 Turn。

显式状态机减少“靠调用顺序约定”的隐式行为，也使非法状态能在接近根因处被拒绝。

## 4. 历史数据的三层存储

项目没有把“历史”混成一个对象，而是按用途分为三层：

| 层次 | 载体 | 生命周期 | 用途 |
|---|---|---|---|
| 语义历史 | `Agent.messages` | 当前进程/会话 | 给模型提供 user/assistant/tool 上下文 |
| 事实状态 | `AgentState` + `TurnState` | 当前进程/会话 | 保存工具计数、文件、验证、Token、耗时等可计算事实 |
| 审计历史 | `logs/session_*.jsonl` | 磁盘持久化 | 逐事件复盘请求、响应、工具结果、错误和时序 |

完整语义历史保留在内存中，但发送给模型的是 `ContextManager` 生成的有界视图；压缩不会修改审计源。运行时元数据（如 `_turn_id`）在请求模型前删除，避免把内部协议泄漏给服务端。

JSONL 选择追加式存储，原因是单条事件独立、故障定位容易、写入开销低、即使进程异常通常也只影响最后一行。每条记录具有 `schema_version` 和单调递增的 `event_seq`，消费端应优先按序号排序。这里使用的是 **append-only event log**，不是完整 Event Sourcing：当前版本不会在启动时通过日志重建 Agent 状态，也不提供跨会话“长期记忆”。

失败 Turn 的部分消息和工具结果仍保留用于审计；系统额外写入不含原始错误详情的失败标记，使下一个 Turn 明确知道“前一回合未完成，可能存在部分副作用”。

## 5. 并发模型

### 5.1 Agent 层：不共享可变会话

`messages`、`AgentState`、`LoopDetector`、Context 诊断字段和多数模型客户端指标都是有顺序含义的可变状态。若多个线程共享一个 Agent，LLM 响应和工具结果可能交叉，破坏 tool-call 协议及 Turn 归属。

因此 V4.1 的选择是：**一个 Agent = 一个串行会话执行单元**。`run_turn()` 使用非阻塞互斥锁拒绝重叠调用。第二步多 Agent 应由 Coordinator 创建多个独立 Worker；每个 Worker 拥有自己的 Agent、LLMClient、ContextManager、LoopDetector 和 State，不共享这些对象。

### 5.2 日志层：同实例线程安全

`SessionLogger` 用锁保护“分配序号 + 追加一行”的临界区，保证同一 Logger 实例中 JSON 行不交错且序号连续。不同 Logger 使用含 UUID 的独立文件，因此正常情况下不会争用同一路径。

该保证只覆盖同一进程内的 Logger 实例；当前没有实现多个进程共同追加同一日志文件的分布式锁。

### 5.3 文件层：锁 + 乐观并发控制

文件修改包含“读取旧值、检查安全、生成新值、写入”的 read-modify-write 序列：

```text
read_file -> sha256(version N)
                     |
edit/write(expected_sha256=N)
                     |
      current version still N ? -- no --> ConcurrentModification
                     |
                    yes
                     v
       stage temp -> fsync -> atomic replace -> version N+1
```

- `RLock` 保证同一 `FileTools` 实例内的临界区串行；
- `expected_sha256` 提供跨实例、跨 Worker 的 Compare-And-Swap 语义；
- 新文件可用 `expected_sha256="missing"` 声明“必须尚不存在”；
- `os.replace` 保证目标路径在旧完整版本和新完整版本之间原子切换；
- 写入异常时清理暂存文件。

这是乐观并发控制：冲突较少时无需长期持锁，发生冲突则重新读取、重新规划。为了兼容旧调用，省略 `expected_sha256` 时仍是 last-writer-wins；后续所有多 Agent 写操作必须传版本，或者使用独立 Git worktree。

## 6. 安全工程

命令策略采用分层防御：可执行文件 allow-list、`shell=False`、单命令语法、超时/输出上限，以及独立的风险分类。Git 解析先跳过 `-C`、`-c` 等全局选项再识别真实子命令，并统一处理 `--flag value` 与 `--flag=value`。未知 Git 子命令按 review 处理，而不是乐观判为 safe。

这体现：

- **最小权限**：只允许完成编码/验证所需能力；
- **fail closed**：解析不清或未知行为默认阻止/审批；
- **完全中介**：每次工具调用都经过 Registry 和 SafetyPolicy；
- **纵深防御**：Prompt、工具参数校验、安全策略和 OS 进程边界彼此独立。

限制也必须明确：允许执行的 Python/测试命令仍可运行仓库代码，因此该策略防止的是误操作，不是恶意代码；不可信项目需要容器或虚拟机隔离。

## 7. 错误处理与恢复

- 外部 API 的瞬态错误采用有界指数退避，认证/参数错误快速失败；
- 工具返回结构化 `{ok, result/error}`，模型可观察失败并调整；
- 最大步数与循环检测保证控制流有界；
- 失败 Turn 被标为 `error`，但已发生的外部副作用不会假装回滚；
- 写文件通过原子替换避免“回滚半个文件”的需求；
- 并发版本冲突返回明确错误，调用者重新读取后再决定，而不是覆盖新数据。

这里遵循“异常安全而非伪事务”原则：跨 LLM、文件和命令无法提供真正 ACID 事务，所以系统准确记录已发生事实，并为重试提供幂等/冲突检测基础。

## 8. 验证策略与可追踪性

测试按风险建立回归矩阵：

- 状态机：多 Turn、失败恢复、并发 Turn 拒绝；
- 协议：上下文压缩后不产生孤立 tool result；
- 一致性：陈旧 SHA 被拒绝、`missing` 创建前置条件、无残留暂存文件；
- 安全：Git 前置选项、等号参数、alias、pip/npm wrapper 绕过；
- 审计：密钥脱敏、并发写日志仍为合法 JSONL、序号连续；
- 端到端：Fake LLM 完成 inspect/edit/validate/final 循环。

单元测试不依赖付费 API，保证快速、确定性回归；真实网关测试用于验证兼容性和集成行为，两者职责分开。`git diff`、测试命令、事件日志和状态摘要共同形成需求—实现—验证的可追踪链。

## 9. 配置管理与演进

`.gitattributes` 固定主要文本格式的换行策略，避免 Windows/Linux 协作产生无意义全文件 Diff。密钥只从环境变量读取，日志和 workspace 由 `.gitignore` 排除。版本号提升为 V4.1 表示兼容性优化，不改变 V4 的主要 CLI 生命周期。

## 10. V5 多 Agent 对既有边界的复用

V5 没有把 peer 通信塞进 `Agent`，而是在上层引入确定性的 `MultiAgentCoordinator`。每个角色独占 Agent、LLMClient、Context、LoopDetector 和 State；Coordinator 只传递经过 Schema 校验且有大小上限的 Blackboard 数据，不共享各角色的原始 message/tool-call 历史。

Planner、Implementer、Reviewer 使用本地工具 allow-list 强制最小权限。计划需要通过 DAG 无环、唯一 ID、依赖存在、字段白名单及验收命令检查。Reviewer 的 `approved` 只是必要条件；Coordinator 还会检查运行时 `commands_run`，没有成功验证证据就自动改判为拒绝。这是“模型负责建议、本地代码负责控制与事实”的延续。

当前写 Worker 严格串行，Reviewer 只读文件但可运行验证命令。全局 LLM call budget、Turn token budget 和 review round 上限分别控制计算资源与反馈循环。具体协议见 [Multi-Agent Collaboration](MULTI_AGENT.md)。后续并行只读 Worker 或 worktree Writer 仍必须遵守第 5 节的一致性边界。
