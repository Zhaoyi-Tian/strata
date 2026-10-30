# 用 dsh 玩 Strata

适配代码在本仓库的 `dsh/`，上下文算法仍由独立仓库 `dsh-strata` 提供。
每次运行只创建一个 dsh Agent 和一个常驻 Python `Env`。dsh 的原生 AgentLoop 调用
`strata_step({"action": "不做"})`，Python 返回交易反馈和下一问。环境结束后，在下一次采样前直接收尾。没有另一套模型循环。

## 安装

需要 Python 3.12+、uv、Node.js 26+ 和 pnpm 11。依赖固定为 dsh `0.2.1-alpha.2`，安装时使用仓库中的 lockfile。
Session JSONL 依赖会静态导入 Node 的 Zstandard API，选择明文日志也不会省去这项运行时依赖。
两个仓库默认放在相邻目录：

```text
story/
  strata/
  dsh-strata/
  .env             # 可选，仅保存 DEEPSEEK_API_KEY
```

从 `strata/` 开始：

```sh
uv sync --frozen
cd ../dsh-strata
pnpm install --frozen-lockfile
pnpm build
cd ../strata/dsh
pnpm install --frozen-lockfile
cd ..
```

`dsh/package.json` 用 `file:../../dsh-strata` 安装本地插件，并声明 `injected: true`，
让插件与 runner 使用同一套 dsh 服务，避免直接链接另一个仓库的 `node_modules` 后出现类实例不兼容。
如果目录不同，改这个依赖路径后重新安装。修改上下文插件后，先在插件仓库构建，再在本仓库 `dsh/` 中运行 `pnpm update dsh-strata`。
依赖安装在 `dsh/node_modules/`，不修改系统 Python 或全局 dsh profile。

## 跑一个短局

在 `strata/` 目录执行：

```sh
node dsh/run.mjs \
  --mode full --seed 0 --config config/dsh-smoke.toml \
  --env-file ../.env \
  --output /Users/tzy/WorkSpace/Temp/strata-dsh/runs
```

也可以在进程环境里设置 `DEEPSEEK_API_KEY` 并省略 `--env-file`。不要把 key 写进 YAML、命令参数或提交到仓库。
短局是两世、每世四天，只用于检查接口。省略 `--config` 就使用默认的四世、每世一百天。

切换上下文模式只改 `--mode`：`full`、`summary`、`notes`。每次都新建一局和一个 Session；不能把同一局中途改成另一种模式作为对照。
不需要先启动交互式 dsh，也不需要安装到 `$DSH_HOME`。

为了在短局里看到压缩或换窗，可以调小窗口，并相应缩小 notes 的缓冲：

```sh
node dsh/run.mjs \
  --mode summary --seed 0 --config config/dsh-smoke.toml \
  --context-tokens 6144 --summary-tokens 2048 \
  --env-file ../.env --output /Users/tzy/WorkSpace/Temp/strata-dsh/runs

node dsh/run.mjs \
  --mode notes --seed 0 --config config/dsh-smoke.toml \
  --context-tokens 8192 --fallback-buffer 2048 --reminder-tokens 1024 \
  --env-file ../.env --output /Users/tzy/WorkSpace/Temp/strata-dsh/runs
```

是否实际触发，以结果里的 `summaryCalls` 和 `windows` 为准。短局和小窗口的分数不当成正式 benchmark 结果。

## 配置

`node dsh/run.mjs --help` 查看入口与可用参数。

| 参数 | 默认 | 用途 |
| --- | --- | --- |
| `--mode` | `notes` | `full / summary / notes` |
| `--seed` | `0` | 世界、按日订单和出生地点的共同种子 |
| `--config` | 游戏默认配置 | Strata TOML，路径相对调用目录；只写要覆盖的项 |
| `--model` | `deepseek-flash` | 交给固定版本的 dsh DeepSeek adapter 解析的模型 ID |
| `--max-tokens` | `8192` | 每次正常模型请求的输出预算，包含服务商计入输出的思考 |
| `--max-requests` | `10000` | 整局模型请求上限，包含摘要；达到上限记为未完成 |
| `--context-tokens` | `81920` | notes 的硬上限、summary 的触发阈值；full 忽略 |
| `--summary-tokens` | `4096` | 摘要输出预算 |
| `--fallback-buffer` | `16384` | notes 保存检查点的缓冲，必须小于可用硬上限 |
| `--reminder-tokens` | `6144` | notes 提醒阈值 |
| `--env-file` | 不加载文件 | 显式读取 API key 的文件 |
| `--output` | `strata/results/dsh/` | 输出根目录；本机建议显式指定上面的 Temp 路径 |

自定义摘要或 notes 提示词，直接在 `dsh/profile.yml` 的 `dsh-strata.config` 下增加插件支持的 `prompts` 字段。
不要改 Python 环境来实现记忆算法。插件的完整参数见相邻仓库的 README。

## 极简 profile

`dsh/profile.yml` 是完整的 Cordis 插件列表，由 `run.mjs` 调用官方 `dsh-app-boot` 加载。
它不是官方 headless/base 的覆盖补丁，也不会读取用户的全局 profile。

只挂载这些部分：

- dsh 的模型、Session、投影、token 计量、system prompt、tools 和 AgentLoop。
- 一个 DeepSeek API-key adapter，启用原生 thinking。
- JSONL Session 持久化、请求与工具执行前的日志 checkpoint。
- Session 查询服务；关闭 SQLite 全文索引，当前会话的过滤和精确读取仍可用。
- `dsh-strata` 上下文插件和本仓库的游戏适配。

模型能调用的工具只有：

| 模式 | 工具 |
| --- | --- |
| `full`、`summary` | `strata_step` |
| `notes` | `strata_step` 加上下文插件的 10 个笔记、历史和换窗工具 |

没有 shell、文件读写、Web、MCP、技能、子代理、todo、自动标题、PTC、官方 compaction、结果裁剪、spill 或图像 offload。
没有自动 API 重试。不会把本地评测日志上传为额外的 DeepSeek Session-log 字段。
任何一个启用的插件未能激活都会终止运行，避免声称在测 summary，实际却退化成 full。

## 环境和记忆的边界

- `Env.reset()` 每局只调用一次；模型没有 reset、truth 或任意 Python 执行工具。
- `env.instructions` 常驻 system，包含玩法、地图、总时长、目标和动作格式。
  “只回一个动作”仅约束 `strata_step.action`，不禁止模型调用记忆工具。
  记笔记、查历史和换窗的使用说明由上下文插件在 notes 模式提供。
- 每次请求通过 dsh 的动态 context 提供 `env.observation()`：当前世数、日期、地点、订单、公开摊子和提问阶段。
  它不包含上次交易的隐藏特质反馈。旧反馈、过往摊子和经验都属于历史，由所选记忆模式负责保存。
- `strata_step` 的结果保留原始反馈。换窗后重新绘制当前画面，但不推进世界，也不恢复已经清掉的经历。
- 死亡时 Python 直接执行“继续”，保留死亡和重生反馈。死亡不额外触发清空或摘要；换窗由上下文插件控制。
- 非法动作不推进日期，反馈给模型纠正；整个 `info` 和内部节点结构不会作为工具结果发送。

## 输出与完成判定

每次运行在输出根目录下建一个唯一子目录：

```text
run.json        运行参数与协议版本 daily-orders-v2
profile.yml     本次使用的 profile 原文
api.jsonl       每次模型请求的完整消息/工具，以及返回流、思考、usage 和耗时
env.jsonl       每次游戏动作、反馈、内部事件、动作后的 truth；仅供评测
sessions/       dsh 原生 Session 日志，包括原始思考、笔记、换窗和摘要
summary.json    完成状态、成绩、调用次数、usage、错误和 Session ID
```

只有环境整局结束，且 runner 在下一步边界正常停止 AgentLoop，`eval_completed` 才为真并输出 `score`，
`termination` 为 `env_done`。这里使用 dsh 的 pre-step 拒绝机制，原生 `turn/end` 的 reason 是 `blocked`；
只有 runner 自己确认的环境终止才算完成，其他 blocked 都不能算完成。结束后不再为最终答复、笔记或摘要追加模型请求。
提前给最终回答、API 错误、摘要失败、请求上限、取消等都输出 `score: null`，进程非零退出。
非法动作次数单独记录；环境按原规则不扣游戏日。完整游玩后成单率为零是正常零分，与未完成不同。

`score` 包含整局每天成单率、各世成单率和第二世起重生头 20 天的成单率。
路上的天、不做的天均留在分母里。usage 保留原始分项，不猜测价格或把缺失 usage 当成零开销。

当前不支持进程重启后续玩同一个 Python 世界。Session 日志可检查原文，但不能只恢复 Session、重新创建 Env 就声称恢复了同一局。

## 对照条件

`daily-orders-v2` 固定了三件事：基础订单由 seed 和**接单的世界日**决定，出生地点由 seed 和世数决定，最后一天出门不会多推进世界一天。
旅行途中不另接单，到达后仍做出发时接到的订单。人物按世界节点编号命名，走访顺序不改变名字；没见过的人仍不预先出现在模型观察里。

因此同配置、同 seed 的世界进程、同一天的新订单及每世出生点一致。不同 agent 的实际路线、见闻和接到哪些订单仍会不同，
三种模式比较的是包含决策在内的整局表现，不是给相同经历后单独测回忆。新协议的分数不能与旧随机流版本混在一起。

## 验证

```sh
uv run python -m unittest discover -s tests
cd dsh
pnpm test
```

Python 测试检查路线对照、生命周期日期、名字、公开快照，以及环境与规则基线的一致性。
内核还独立检查逐日结算、最后一天旅行和死亡边界的日期与计分，不只比较两种接口是否一致。
Node 测试使用脚本模型，经过真实 profile、常驻 Python 环境和原生 AgentLoop，验证三种模式、
跨窗恢复、连续摘要、思考日志、真值隔离，以及提前结束、API 错误和请求上限的未完成判定。

运行依赖安装在本地 `dsh/node_modules/`；需要重新安装时可删除它，保留源码和 lockfile。pnpm 的工具缓存由 pnpm 管理。
对局日志保留在指定的输出目录，测试临时目录自动清理。
