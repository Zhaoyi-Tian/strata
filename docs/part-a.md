# Part A：五项可独立开关的机制

本版把传闻、指称订单、改主意、前瞻任务和干扰信息接入同一套 `Game` / `Env`。世界的继承、变化概率和随机流不变。正式机制协议为 `part-a-v1`；全部关闭仍使用 `daily-orders-v2`。

[首轮正式运行结果](experiments/part-a-2026-11-26.md)报告 full 模式下的连续十世表现，附配置、逐世成绩、机制分项、完整动作轨迹与离线重算脚本。

## 先看故事，再自己玩

```powershell
# 本仓库已建立虚拟环境时
.\.venv\Scripts\python.exe -m strata.demo
.\.venv\Scripts\python.exe -m strata.env --config config/part-a.toml --seed 0
```

使用 uv 的环境对应 `uv run python -m strata.demo` 和 `uv run python -m strata.env --config config/part-a.toml --seed 0`。`strata --config config/part-a.toml` 也会进入同一个文本交互入口。

运行 `python -m strata.demo` 可生成完整演示文字。演示固定初始货物、守信值，使用一个地区的三个村、六天短局，并提高事件触发率。演示控制器能读取真值来安排行动，**不是被测 agent，其成绩不能作为 benchmark 结果**。没有单独的演示结算引擎。

当前演示里：第一天在柳溪接到采购、传闻和捎话委托，东家随后改要盐；第二天去石门主动给茶客传话；第六天的订单通过第二天的买卖指向屠户。所有人名、货物、动作和结果均来自实际对局。

文字初版统一在 `config/worldview.toml`：开场为 `part_a_intro`，事件在 `[lines]`，口信、闲聊和机制规则在 `[mechanism_text]`。公开画面不显示真假标签、指称答案和待办清单。

## 开关与参数

`config/default.toml` 全部关闭；`config/part-a.toml` 五项全开。配置文件递归覆盖默认值，可以只写一项，例如仅开传闻：

```toml
[mechanisms.rumor]
enabled = true
rate = 0.5
min_delay = 0
max_delay = 5
all_truthful = false
credibility_slot = "守不守信"
```

| 配置表 | 参数及默认值 | 含义 |
|---|---|---|
| `rumor` | `rate=0.5`，`min_delay=0`，`max_delay=5` | 每次接单时的传闻率，历史日期相距的世界日范围 |
| `rumor` | `all_truthful=false`，`credibility_slot="守不守信"` | 为真时一律如实转述历史；否则说话者该槽位为首个值时诚实，其他值时声称另一个值 |
| `reference_orders` | `rate=0.2`，`max_hops=2` | 指称触发率；跳数支持 1 或 2 |
| `revisions` | `rate=0.1`，`max_revisions=2` | 抵达后、购买前两个时点分别抽一次；每单最多修订 0–2 次 |
| `prospective` | `rate=0.15`，`max_pending=2` | 接单时委托发布率；同时处于待触发或执行窗口的数量上限 |
| `distraction` | `useful_ratio=0.5`，`max_per_news=2` | 有用消息比例目标及每次闲聊上限 |

概率范围为 `[0,1]`，日期和数量使用整数。五项都有独立的 `enabled`，支持 32 种组合。调用 `Env(cfg, mechanisms=[])`、`Game(cfg, mechanisms=[])` 或 `play(..., mechanisms=[])` 可覆盖配置并关闭全部；传入具体列表则只使用该列表，不再自动追加配置机制。省略或传 `None` 时使用配置。

每个机制按 seed、机制名、事件日期和事件身份派生独立随机数，不使用 `world.rng`。相同 seed、配置和动作可重放。开关改变玩家经历后，后续指称候选和委托机会可能随实际历史改变；独立随机流不意味着不同经历也会生成完全相同的任务。

## 具体行为

### 传闻

在发布订单和摊子后出现，包含说话者、对象、世界日期和所述特质。延迟从已经保存的历史快照取事实，不能把当前值伪装成过去值；历史覆盖路途、死亡空转和重生，世界第 0 天是开局初始状态。

是否说谎由传播时说话者的特质决定。审计分别记录“说法与历史不符”和“历史事实与现在不同”；二者可以同时发生。一条编造的旧闻也可能碰巧与现在一致。没有符合延迟范围的历史时不发消息。

### 指称订单

一跳引用“世界第 N 天卖给你某货的人”；两跳引用“世界第 N 天东家那张口信里指定的人”。只使用玩家已经收到反馈的交易或已经听到的指称订单。每个世界日最多一笔交易、一张新订单，因此指向唯一。

发布时从当前仍出售所需可见货物的历史对象中选择；没有候选就使用普通订单。指定对象之外的人即使货物、隐藏特质均满足，也不能完成该单；反馈仍如实展示验货结果，不把认错人说成短秤。世界后来变化或路途延迟仍可能让原本可买的货消失，这属于环境变化。

### 改主意

只修改当前尚未结束的订单，不积压多张订单。保留接单日和订单身份，追加版本记录。跨区时先扣路程，抵达后仍处理出发那一单。路上寿命用尽不会发生抵达修订。

留村/抵达后、第一次选择交易前各有一次检查，传话、无效动作、重绘不重抽。最多两次修订均可发生在同一天。若快捷命令 `找 某人` 的中间阶段收到改口，本次购买暂停，玩家需要重新选择。

修订只改变一个可见货物槽位。普通订单的新货必须有人在当前村出售；指定人物订单的新货必须是指定人物当前出售的货物。没有不同且可买的新货就不修订，避免两项机制组合制造确定无解的订单。隐藏要求和指定对象保留。

### 前瞻任务

输入 `传话 <人名> <口信>`，只能向现场的人传话。空格、全角字符和标点规范化后比较；不进行语义改写或调用模型判分。有效传话不推进日期、不改变订单、不结束采购阶段。

委托发布时目标在别村。首次之后抵达（包括重生地点）打开执行窗口；采购完成、跳过当天采购或离开时关闭窗口。没有到过目标村的委托跨世保留。关闭后补说不算完成；同一收件人的同一口信不会在一局中重新发布，重复动作不重复得分。

传话反馈统一表示对方已听到，不提示当前是否有委托、不告诉你正确口信。系统只在任务最初发布时告知，后来画面、动作列表和换窗重绘都不会补回待办。`legal_actions()` 只列可枚举的采购动作，传话格式见常驻说明。

独立指标：`issued`、`opportunities`、`completed`、`missed`、`untriggered`、`incorrect`、`duplicates` 和 `completion_rate`。完成率分母只计实际获得执行机会的任务；无机会时为 `null`。采购分数不加传话奖励。公开最终统计只在整局结束后提供。

### 干扰信息

不改世界和订单。每次接单后，根据当次传闻和委托数量补充闲聊，数量受上限和可用台词数约束，因此 `useful_ratio` 是目标而非精确保证。没有有用消息且比例小于 1 时仍可发一条闲聊，支持独立启用；比例为 1 时不加闲聊，比例为 0 时使用上限。

## 接口与证据

`Game` 负责全部机制状态和日期，`View` 仅把公开事件渲染成文字。保留 `order(game, want)` / `news(game)`，新增生命周期挂钩见 `src/strata/mechanisms/__init__.py`。结构化传话动作是 `DeliverMessage(person, message)`，经 `Game.step()` 执行。`Ask.reference` 只有公开指称表达，正确对象不放进公开快照。

`game.record()` 写入追加式私有审计；`game.say()` 仅传递可展示内容。`info.mechanism_events` 是本次动作新增的审计。`env.truth().mechanisms` 包含订单身份、版本、指称答案及各机制状态。不要将 `info` 或 `truth` 发给被测模型。

| 事件 | 主要归因证据 |
|---|---|
| `rumor` | 说话者、对象、传播日、所述日期、历史值、声称值、当前值、继承来源、是否编造/过期 |
| `reference_order` | 公开表达、正确对象、跳数、前置订单身份 |
| `order_issued` / `revision` | 订单身份、版本、修改前后要求、指定对象 |
| `choice` / `settlement` | 实际选择、有效要求、该人真实特质、成败及是否选错指定对象 |
| `task_issued` / `task_opportunity` / `task_missed` / `message_delivered` | 委托内容、机会日期、关闭状态、尝试结果 |
| `distraction` | 插入的无关消息，可用于开关对照 |

这些记录支持离线核验事实和重新归因，不把心理原因直接当成已知事实。“遗忘/没想起/轻信”仍需结合 Harness 的记忆转储及决策证据。调整归因时可读取已有日志，不必再请求模型。

## dsh 与验证

```sh
node dsh/run.mjs --mode full --seed 0 --config config/part-a.toml --output results/part-a
```

Python 适配器沿用原有 JSONL 动作协议，接受传话。`env.jsonl` 开场记录完整游戏配置及初始机制审计，每步记录公开反馈、私有事件和真值。`run.json` 保存实际协议和机制参数，`summary.json` 的 `score.mechanisms.prospective` 保存独立传话成绩。不同协议的成绩分开报告。

原有五个规则基线还没有消费新消息或解析指称，故 `stratabench` 命令在机制开启时明确拒绝跑分；它们的全关成绩仍应保持不变。该限制不影响文本环境、dsh 或自行接入的机制感知 agent。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

测试包含 32 种组合、独立触发、全关基线指纹、重放与重置、历史真值、两跳指称、连续修订、跨区及死亡边界、传话机会与重复提交、dsh Python 边界和真实故事演示。Node 的完整 AgentLoop 测试另需 Node 26+、pnpm 及相邻 `dsh-strata` 依赖，见 [dsh.md](dsh.md)。
