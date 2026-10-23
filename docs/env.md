# 文本接口 `strata.env`

让 LLM（或任何读文字、写动作的 agent）来玩采办。规则和 `play()` 是同一份（`Game.run()`），只是换成一问一答，所以规则基线通过文本接口玩，成绩和回调版每一天都一样（`tests/test_env.py` 在查）。

**这份文档就是接口约定。** 签名以 `src/strata/env.py` 为准；要改签名，先在群里说一声。

## 一分钟上手

```python
from strata import Env, load

env = Env(load(), seed=0)       # load("config/xxx.toml") 换配置；seed 换世界
env.instructions                # 常驻说明：开场白 + 地图 + 动作格式。放 system prompt，整局不变
obs = env.reset()               # 第一天的订单、本村的摊子，问你今天怎么办
obs, done, info = env.step("找 老秦")
```

自己打字玩（Windows 也行）：`python -m strata.env [--seed N]`

## 一天怎么走

每天一到两问：

| 问 | `env.ask.kind` | 能回的动作 |
|---|---|---|
| 今天怎么办？ | `go` | `找 <人名>` / `不做`（都是留在本村做）、`去 <村名>`、`留下` |
| 找谁？（去了别村，或说了「留下」之后） | `choose` | `找 <人名>` / `不做` |
| 一世到头、下一世开始前 | `death` | 回什么都行，runner 直接回 `继续` |

- 同一地区里串村当天就到；去别的地区路上走一天，那天算没成单。
- `找` 了一个不卖这样货的人，等于不做（原版规则）。
- **看不懂的动作不消耗天数**：返回提示，原样再问一次，`info["parse_ok"] = False`。可以少加几个字：`找老秦。`、`「找 老秦」` 都认；`找 老秦，因为他守信` 不认。
- 动作词（找 / 不做 / 去 / 留下）是协议的一部分，换皮也不变。

## runner 的写法（给测评、Harness）

```python
env = Env(load(), seed=seed)
system = env.instructions
obs = env.reset()
while not env.done:
    if env.life_ended:            # 失忆协议在这里：写遗书、清空上下文。全上下文模式什么都不做
        agent.end_life(obs)
        action = "继续"           # 这一问不必调 LLM
    else:
        action = agent.act(obs)
    obs, done, info = env.step(action)
    log.write(...)                # 见下面 info 的字段
score = env.lives                 # 每一世每天成没成单（list[list[bool]]）
```

最后一世到头直接 `done`，没有 `death` 这一问。

## API

| 名字 | 是什么 |
|---|---|
| `Env(cfg=None, seed=None, mechanisms=())` | 一局。`cfg` 来自 `strata.load()`；`mechanisms` 见 `src/strata/mechanisms/__init__.py` |
| `env.instructions` | 常驻说明（str） |
| `env.reset() -> str` | 开局；再调一次就从头再来（同一个 seed，同一个世界） |
| `env.step(action) -> (obs, done, info)` | 回一个动作 |
| `env.legal_actions() -> list[str]` | 此刻能回的所有动作（给不给 agent 看，由实验设置决定） |
| `env.life_ended` | 一世刚到头、下一世还没开始 |
| `env.done` | 整局结束 |
| `env.lives` | 已经过完的每一世，每天成没成单 |
| `env.truth() -> dict` | 此刻的真值，**只给评测、归因和全知用，绝不能进 agent 的上下文** |
| `env.name(n)` | 节点 n 在文字里叫什么；agent 还没见过的人返回 `None` |
| `env.ask` | 当前这一问的结构化版本（`Ask`：kind、day、here、want、stalls），给规则基线和测试用，不给 LLM |
| `env.world` | 世界本身（真值），同上 |

### `info`（每一步）

```python
{"life": 1, "day": 7, "day_in_life": 6,
 "asked": "choose",            # 这一步回答的是哪一问
 "phase": "go",                # 下一问；整局结束是 "done"
 "action": "不做", "parse_ok": True, "error": None,
 "life_ended": False,          # 这一步里有一世到头了（包括最后一世）
 "events": [{"kind": "skip"}, {"kind": "order", "day": 7, "village": 38, "卖什么": "铁", "守不守信": "守信"},
            {"kind": "stalls", "stalls": {39: {"卖什么": "茶"}, 40: {"卖什么": "铁"}, 41: {"卖什么": "茶"}, 42: {"卖什么": "茶"}}}]}
```

`events` 是这一步发生的事，和观察文字一一对应。里面的村和人都是**节点编号**（world 里的下标），名字用 `env.name(n)` 查。种类有 order / stalls / walk / travel / done / fail / skip / death / rebirth，A 的机制会再加。

### `truth()`

```json
{"day": 2, "life": 1, "day_in_life": 1, "here": 11, "want": {"卖什么": "铁", "守不守信": "守信"},
 "nodes": {
  "0":  {"name": "灰盐原", "layer": "地区", "parent": null,
         "卖什么":   {"value": "铁", "own": true,  "source": 0,  "source_layer": "地区", "since": 0},
         "守不守信": {"value": "短秤", "own": true, "source": 0,  "source_layer": "地区", "since": 0}},
  "11": {"name": "柳溪", "layer": "村", "parent": 0,
         "卖什么":   {"value": "铁", "own": false, "source": 0,  "source_layer": "地区", "since": 0}, "...": "..."},
  "12": {"name": "老秦", "layer": "人", "parent": 11,
         "卖什么":   {"value": "铁", "own": false, "source": 0,  "source_layer": "地区", "since": 1},
         "守不守信": {"value": "守信", "own": true, "source": 12, "source_layer": "人",   "since": 0}}}}
```

每个节点每个槽位：`value` 表现出来的值；`own` 是不是自己的值；`source` / `source_layer` 由哪个节点、哪一层决定；`since` 表现值上次变是哪天（0 = 开局以来没变过）。归因（过时、错误泛化……）靠的就是这几项。

## 示例对局

分层推断通过文本接口玩 seed 0（默认世界）。`>` 后面是动作，其余是 `reset()` / `step()` 返回的观察。

开头：

```text
第 1 天，你在柳溪醒来。东家捎来口信：要一批盐，得找个守信的人买。
老秦的摊上摆着铁，阿巧的摊上摆着铁，铁匠的摊上摆着铁，瞎眼婆婆的摊上摆着铁。
今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）
> 去 石门
你沿着田埂走到石门。
货郎的摊上摆着盐，船娘的摊上摆着茶，刀客的摊上摆着茶，书生的摊上摆着盐。
找谁？（找 <人名> / 不做）
> 找 货郎
你从货郎手里买下盐，回去过秤，少了两成——他短秤。东家沉下了脸。
第 2 天，你在石门醒来。东家捎来口信：要一批铁，得找个守信的人买。
货郎的摊上摆着盐，船娘的摊上摆着茶，刀客的摊上摆着茶，书生的摊上摆着盐。
今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）
> 去 柳溪
你沿着田埂走到柳溪。
老秦的摊上摆着铁，阿巧的摊上摆着铁，铁匠的摊上摆着铁，瞎眼婆婆的摊上摆着铁。
找谁？（找 <人名> / 不做）
> 找 老秦
你从老秦手里买下铁，回去过秤，分量足足的。东家很满意。
第 3 天，你在柳溪醒来。东家捎来口信：要一批茶，得找个守信的人买。
……
```

翻山去别的地区：

```text
第 5 天，你在石门醒来。东家捎来口信：要一批盐，得找个守信的人买。
货郎的摊上摆着盐，船娘的摊上摆着茶，刀客的摊上摆着茶，书生的摊上摆着盐。
今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）
> 去 霜桥
你翻山去霜桥，路上走了 1 天。
绣娘的摊上摆着茶，樵夫的摊上摆着茶，渔夫的摊上摆着茶，乞丐的摊上摆着茶。
找谁？（找 <人名> / 不做）
> 不做
今天没找着合适的人，你空着手歇了一天。
第 7 天，你在霜桥醒来。东家捎来口信：要一批铁，得找个守信的人买。
……
```

一世到头、重生：

```text
第 100 天，你在松湾醒来。东家捎来口信：要一批茶，得找个守信的人买。
信使的摊上摆着铁，农妇的摊上摆着铁，更夫的摊上摆着铁，药婆的摊上摆着铁。
今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）
> 去 苇塘
你翻山去苇塘，路上走了 1 天。
这一世到头了。你闭上眼，世间又过了 300 天。
（这一世结束了。回任意内容，进入下一世。）          ← env.life_ended 为真
> 继续
你在一个陌生的身子里醒来，这是第 2 世。前世的事，你都还记得。
第 402 天，你在白垩渡醒来。东家捎来口信：要一批盐，得找个守信的人买。
郎中的摊上摆着铁，屠户的摊上摆着茶，茶客的摊上摆着茶，牧童的摊上摆着铁。
今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）
```

## 给玩法 A 的挂钩

新机制继承 `strata.mechanisms.Mechanism`，Game 每天在两个时刻调它：`order(game, want)`（订单刚生成，可以改）和 `news(game)`（订单和摊子说完、拿主意之前，可以 `game.say(...)` 加话）。机制自己开随机数，不要动 `world.rng` 和 `game.orders`，否则开不开机制世界就不一样了。详见 `src/strata/mechanisms/__init__.py`。

## 不变量

- 只改接口时，`tests/test_env.py` 里的 `BEFORE`（原版规则下各基线的成绩和逐日指纹）必须不变。改了规则它会变，那是对的：重新跑一遍，同步 README 里的表。
- 同一个 seed：同一个世界、同一串订单，和 agent 怎么走无关。

## 还没定的

- **人名按出场先后起**（`view.py` 原来的设计）：不同 agent 走的路线不同，同一个人在两局里可能叫不同的名字。对 agent 没影响；跨 agent 比较时请用节点编号（`events`、`truth()` 里都是编号）。要不要改成按编号固定起名，等照亿定。
- `legal_actions()` 给不给 LLM 看：给了就少了格式错误，但也提示了"这里有哪些人"。建议作为实验设置的一个开关，默认不给。
