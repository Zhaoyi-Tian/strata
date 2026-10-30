"""采办内核：显式持有阶段、位置、订单与逐日成绩。

start() 开局，step(answer) 回答当前的 Ask；ask / done 从内核状态导出。
旅行、交易和不做都经过同一个逐日结算入口，寿命用完即结束这一世。
World 只管世界变化，接口只翻译动作，View 只把节点和事件写成文字。
世界、按日订单和每世出生地点使用独立的随机数，走法不改变外部条件。
"""

import random
from dataclasses import dataclass, field
from typing import Literal

from .world import World


@dataclass(frozen=True)
class Ask:
    """当前决策的公开快照；村和人统一使用世界节点编号。

    go：去哪，回一个村（回 here 就是留下）。
    choose：找谁，回 stalls 里的一个人或 None（不做）。
    death：下一世开始之前，回什么都行；可在此做独立定义的记忆干预。
    """

    kind: Literal["go", "choose", "death"]
    day: int
    here: int
    want: dict = field(default_factory=dict)
    stalls: dict = field(default_factory=dict)


class Game:
    """一局采办。所有推进都经 start / step；say 和 observe 只通知发生的事。"""

    def __init__(self, cfg: dict, say=None, observe=None, mechanisms=()):
        self.cfg, g, self.slots = cfg, cfg["game"], cfg["view"]["slots"]
        for key, minimum in (("lives", 1), ("life", 1), ("gap", 0)):
            if type(g[key]) is not int or g[key] < minimum:
                raise ValueError("lives/life must be positive integers; gap must be a nonnegative integer")
        self.world = World(g["seed"], {s["name"]: s["values"] for s in self.slots}, **cfg["world"])
        self.visible = [s["name"] for s in self.slots if s["visible"]]
        self.hidden = [s["name"] for s in self.slots if not s["visible"]]
        self.say = say or (lambda kind, **kw: None)
        self.observe = observe or (lambda day, p, seen: None)
        self.mechanisms = list(mechanisms)
        self.phase: Literal["new", "go", "choose", "death", "done"] = "new"
        self.life, self.here = 0, None
        self.want, self.stalls = {}, {}
        self.log: list[bool] = []                               # 当前世已结算的每天；结束时加入 lives
        self.lives: list[list[bool]] = []                       # 已结束的每一世

    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def ask(self) -> Ask | None:
        """快照不持有另一份进度，修改其中的字典也不改变内核。"""
        if self.phase in ("new", "done"):
            return None
        if self.phase == "death":
            return Ask("death", self.world.day, self.here)
        return Ask(self.phase, self.world.day, self.here, dict(self.want),
                   {p: dict(seen) for p, seen in self.stalls.items()})

    @property
    def days_played(self) -> int:
        """已结算的游戏日；死亡边界不重复计算刚加入 lives 的 log。"""
        return sum(map(len, self.lives)) + (len(self.log) if self.phase in ("go", "choose") else 0)

    def order_at(self, day: int) -> dict:
        """某个世界日的基础订单；路上跳过几天也不会挪动后面的订单。"""
        rng = random.Random(f"{self.cfg['game']['seed']}:orders:{day}")
        return {s["name"]: rng.choice(s["values"]) if s["visible"] else s["values"][0] for s in self.slots}

    def start(self) -> Ask:
        if self.phase != "new":
            raise RuntimeError("这一局已经开始了")
        self._begin_life()
        return self.ask

    def step(self, answer: int | None) -> Ask | None:
        """回答当前阶段；非法节点在推进前拒绝，不消耗游戏日。"""
        if self.phase == "go":
            if type(answer) is not int or answer not in self.world.villages:
                raise ValueError("目的地必须是一个村的节点编号")
            self._go(answer)
        elif self.phase == "choose":
            if answer is not None and (type(answer) is not int or answer not in self.stalls):
                raise ValueError("只能找当前村摊子上的人")
            self._choose(answer)
        elif self.phase == "death":
            self._afterlife()
        else:
            raise RuntimeError("先调 start()" if self.phase == "new" else "这一局已经结束了")
        return self.ask

    def _begin_life(self):
        g = self.cfg["game"]
        self.life += 1
        self.here = random.Random(f"{g['seed']}:spawn:{self.life}").choice(self.world.villages)
        self.log = []
        if self.life > 1:
            self.say("rebirth", life=self.life)
        self.world.step()                                     # 第一日；之后只在逐日结算和死后空转时推进
        self._order()

    def _look(self):
        self.stalls = {p: {s: self.world.value(p, s) for s in self.visible} for p in self.world.residents[self.here]}
        for p, seen in self.stalls.items():
            self.observe(self.world.day, p, seen)

    def _order(self):
        self.phase = "go"
        self.want = self.order_at(self.world.day)
        self._look()
        for m in self.mechanisms:
            self.want = m.order(self, self.want)
        self.say("order", day=self.world.day, village=self.here, **self.want)
        self.say("stalls", stalls=self.stalls)
        for m in self.mechanisms:
            m.news(self)

    def _go(self, dest):
        if dest != self.here:
            days = self.world.distance(self.here, dest)
            self.say("travel" if days else "walk", village=dest, days=days)
            for _ in range(days):
                if not self._settle_day("road"):
                    return                                   # 最后一天还在路上：不到达，也不再推进一天
            self.here = dest
            self._look()
            self.say("stalls", stalls=self.stalls)
        self.phase = "choose"

    def _choose(self, person):
        if person is None or any(self.stalls[person][s] != self.want[s] for s in self.visible):
            alive = self._settle_day("skip")
        else:
            success = all(self.world.value(person, s) == v for s, v in self.want.items())
            alive = self._settle_day("done" if success else "fail", person)
        if alive:
            self._order()

    def _settle_day(self, outcome: Literal["road", "skip", "done", "fail"], person=None) -> bool:
        """结算一天，再进入下一游戏日或死亡边界；返回是否仍活着。"""
        self.log.append(outcome == "done")
        if outcome in ("done", "fail"):
            seen = {s: self.world.value(person, s) for s in self.hidden}
            self.observe(self.world.day, person, seen)
            self.say(outcome, person=person, **(self.want | seen))
        elif outcome == "skip":
            self.say("skip")
        g = self.cfg["game"]
        if len(self.log) == g["life"]:
            self.lives.append(self.log)
            self.phase = "death"
            self.say("death", gap=g["gap"])
            if self.life == g["lives"]:
                self._afterlife()
            return False
        self.world.step()
        return True

    def _afterlife(self):
        for _ in range(self.cfg["game"]["gap"]):
            self.world.step()
        if self.life == self.cfg["game"]["lives"]:
            self.phase = "done"
        else:
            self._begin_life()

    def play(self, make_agent) -> list[list[bool]]:
        """回调适配；决策与文本接口一样交给 start / step，不包含规则。"""
        agent = make_agent(self.world, self.visible)
        self.observe = agent.observe
        ask = self.start()
        while ask is not None:
            if ask.kind == "go":
                answer = agent.go(ask.day, ask.here, ask.want, ask.stalls)
            elif ask.kind == "choose":
                answer = agent.choose(ask.day, ask.want, ask.stalls)
            else:
                answer = None
            ask = self.step(answer)
        return self.lives


def play(cfg: dict, make_agent, say=None, mechanisms=()) -> list[list[bool]]:
    """新建一局，让 make_agent(world, visible) 通过 go / choose / observe 玩完。"""
    return Game(cfg, say=say, mechanisms=mechanisms).play(make_agent)
