# 文本接口 `strata.env`

让 LLM（或任何读文字、写动作的 agent）来玩采办。文本接口和回调式 `play()` 都使用 `Game.start()` / `Game.step()`，所以规则基线通过文本接口玩，成绩和回调版每一天都一样（`tests/test_env.py` 在查）。

接口签名以 [src/strata/env.py](../src/strata/env.py) 为准。

## 一分钟上手

```python
from strata import Env, load

env = Env(load(), seed=0)       # load("config/xxx.toml") 换配置；seed 换世界
env.instructions                # 常驻说明：开场白 + 地图 + 动作格式。放 system prompt，整局不变
obs = env.reset()               # 第一天的订单、本村的摊子，问你今天怎么办
obs, done, info = env.step("不做")  # 也可以按当前画面找人或去别村
```

在仓库目录打字玩（Windows 也行）：`uv run python -m strata.env --seed 0`。

## 一天怎么走

每天一到两问：

| 问 | `env.ask.kind` | 能回的动作 |
|---|---|---|
| 今天怎么办？ | `go` | `找 <人名>` / `不做`（都是留在本村做）、`去 <村名>`、`留下` |
| 找谁？（去了别村，或说了「留下」之后） | `choose` | `找 <人名>` / `不做` |
| 一世到头、下一世开始前 | `death` | 回什么都行，runner 直接回 `继续` |

- 同一地区里串村当天就到；去别的地区路上走一天，那天算没成单。
- `找` 了一个不卖这样货的人，等于不做。找了卖所需货物的人，无论成单还是失败，都会获知其隐藏特质。
- **看不懂的动作不消耗天数**：返回提示，原样再问一次，`info["parse_ok"] = False`。允许省略空格或加标点：`找铁匠。`、`「找 铁匠」` 都认；`找 铁匠，因为他守信` 不认。
- 动作词（找 / 不做 / 去 / 留下）是协议的一部分，换皮也不变。

## runner 的写法（给测评、Harness）

```python
env = Env(load(), seed=seed)
system = env.instructions
obs = env.reset()
while not env.done:
    if env.life_ended:            # 记忆干预由实验另行定义；这里只续到下一世
        action = "继续"           # 这一问不必调 LLM
    else:
        action = agent.act(obs)
    obs, done, info = env.step(action)
    log.write(...)                # 见下面 info 的字段
score = env.lives                 # 每一世每天成没成单（list[list[bool]]）
```

最后一世到头直接 `done`，没有 `death` 这一问。
是否在死亡时做记忆干预由实验另行定义。[dsh 适配](dsh.md) 直接续局，不额外清空上下文。

## API

| 名字 | 是什么 |
|---|---|
| `Env(cfg=None, seed=None, mechanisms=())` | 一局。`cfg` 来自 `strata.load()`；`mechanisms` 见 `src/strata/mechanisms/__init__.py` |
| `env.instructions` | 常驻说明（str） |
| `env.reset() -> str` | 开局；再调一次就从头再来（同一个 seed，同一个世界） |
| `env.step(action) -> (obs, done, info)` | 回一个动作 |
| `env.legal_actions() -> list[str]` | 此刻能回的所有动作（给不给 agent 看，由实验设置决定） |
| `env.observation() -> str` | 当前完整公开画面，用于换窗后重绘；不包含过往交易反馈，不推进世界 |
| `env.life_ended` | 一世刚到头、下一世还没开始 |
| `env.done` | 整局结束 |
| `env.lives` | 已经过完的每一世，每天成没成单 |
| `env.truth() -> dict` | 此刻的真值，**只给评测、归因和全知用，绝不能进 agent 的上下文** |
| `env.name(n)` | 节点 n 在文字里叫什么；agent 还没见过的人返回 `None` |
| `env.ask` | 当前这一问的结构化快照（`Ask`：kind、day、here、want、stalls）；开局前和整局结束后为 `None`。给规则基线和测试用 |
| `env.world` | 世界本身（真值），同上 |

### `info`（每一步）

默认配置、seed 0 开局后执行一次 `不做`，返回：

```python
{'life': 1,
 'day': 2,
 'day_in_life': 1,
 'asked': 'go',
 'phase': 'go',
 'action': '不做',
 'parse_ok': True,
 'error': None,
 'life_ended': False,
 'events': [{'kind': 'skip'},
            {'kind': 'order', 'day': 2, 'village': 1, '卖什么': '铁', '守不守信': '守信'},
            {'kind': 'stalls',
             'stalls': {2: {'卖什么': '茶'}, 3: {'卖什么': '茶'}, 4: {'卖什么': '茶'}, 5: {'卖什么': '茶'}}}]}
```

`asked` 是本次回答的阶段，`phase` 是下一阶段；`life_ended` 表示这次动作中发生了死亡。
`day` 包含死后空转的世界日，`day_in_life` 是当前世已经结算的游戏日数，第一天尚未结算时为 0。

`events` 是这一步发生的事，和观察文字一一对应。里面的村和人都是**节点编号**（world 里的下标），名字用 `env.name(n)` 查。种类有 order / stalls / walk / travel / done / fail / skip / death / rebirth，自定义机制可增加事件。

### `truth()`

同一时刻的真值，以下仅节选铁匠这个节点：

```json
{
  "day": 2,
  "life": 1,
  "day_in_life": 1,
  "here": 1,
  "want": {
    "卖什么": "铁",
    "守不守信": "守信"
  },
  "nodes": {
    "2": {
      "name": "铁匠",
      "layer": "人",
      "parent": 1,
      "卖什么": {
        "value": "茶",
        "own": true,
        "source": 2,
        "source_layer": "人",
        "since": 0
      },
      "守不守信": {
        "value": "短秤",
        "own": false,
        "source": 1,
        "source_layer": "村",
        "since": 0
      }
    }
  }
}
```

每个节点每个槽位：`value` 表现出来的值；`own` 是不是自己的值；`source` / `source_layer` 由哪个节点、哪一层决定；`since` 表现值上次变是哪天（0 = 开局以来没变过）。归因（过时、错误泛化……）靠的就是这几项。

## 示例对局

在仓库目录运行下面的代码，可查看同区移动、交易、跨区旅行和死亡重生的原始反馈。
短局使用 `config/dsh-smoke.toml`：两世、每世四天、死后空转十天。

```python
from strata import Env, load

env = Env(load("config/dsh-smoke.toml"), seed=0)
print(env.reset())
for action in ("去 柳溪", "找 绣娘", "去 鸦岭", "不做", "去 白垩渡", "继续"):
    print(">", action)
    observation, done, info = env.step(action)
    print(observation)
```

第一天去柳溪，当天可以交易；第二天出发去鸦岭，第三天到达后仍处理出发时的订单。
第四天再次跨区时寿命用完，停在死亡阶段；回答 `继续` 后，第二世从世界第 15 天开始。

## 自定义机制

新机制继承 `strata.mechanisms.Mechanism`，Game 每天在两个时刻调它：`order(game, want)`（基础订单已按日生成，可以改）和 `news(game)`（订单和摊子说完、拿主意之前，可以 `game.say(...)` 加话）。机制自己按日取随机数，不要动 `world.rng`；这样调用次数不同也不会让后续外部条件漂移。详见 `src/strata/mechanisms/__init__.py`。

## 不变量

- 只改接口时，`tests/test_env.py` 里的 `BEFORE`（`daily-orders-v2` 下各基线的成绩和逐日指纹）必须不变。改了规则需更新测试期望和规则说明。
- 同配置、同 seed：同一天的世界状态、同一接单日的基础订单、每世出生地点和生命周期日期固定。旅行途中不另接单。
- 人名按世界节点编号固定，走访顺序不改变名字；未见过的人仍返回 `None`。

## 内核与显示边界

`Game` 持有全部玩法进度：`phase`、`life`、`here`、`want`、`stalls`、当前世的 `log`、已结束各世的 `lives`。
世界日和世界随机状态由 `game.world` 持有，没有生成器暂停位置中的隐含进度。

`Game.start()` 只能调用一次，随后用 `Game.step(answer)` 回答当前阶段。
`go` 回村节点，`choose` 回人节点或 `None`，`death` 回任意内容以续局；`new / done` 不能执行动作。
`game.ask` 是从当前状态生成的公开快照，`game.done` 从阶段导出。
`Env` 只把文字动作翻成这些回答，再把事件显示成文字，不持有另一份阶段和结束标记。

旅行中的一天、不做的一天和交易的一天，都在 `Game._settle_day()` 记一条成绩，并进入下一天或死亡。
满寿命就停在当天；路上死亡不算到达，不再额外推进一天。死亡问答不计游戏日。
为保持 `daily-orders-v2` 行为，最后一世结束后仍推进一次配置的空转期，再标为 `done`。
`game.days_played` 只数游戏日，死亡时不会把当前 `log` 和已结束的 `lives` 重复相加。

内核、事件、`Ask` 和 `View.name(node)` 中的村、人、地区统一使用世界节点编号。
`View(view_config, world)` 在显示时按地图顺序给地区和村起名，按节点给人起名；`View.map()` 不再重复传地图尺寸。
原来的 `Game.run()` 生成器已移除；回调式调用可继续用 `play(cfg, make_agent)`，或给一个已创建的 `Game` 调用 `game.play(make_agent)`。

`tests/test_game.py` 独立检查不同走法和寿命下的日期、路程、得分天数及死亡边界；
这些检查不以文本版和回调版相互相等作为唯一依据。

## 可选动作列表

`legal_actions()` 可用于调试或自定义 runner。当前 dsh 接入提供动作格式和公开画面，不额外发送这个列表。
