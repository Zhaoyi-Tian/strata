"""采办内核：显式持有阶段、位置、订单与逐日成绩。

start() 开局，step(answer) 回答当前的 Ask；ask / done 从内核状态导出。
旅行、交易和不做都经过同一个逐日结算入口，寿命用完即结束这一世。
World 只管世界变化，接口只翻译动作，View 只把节点和事件写成文字。
世界、按日订单和每世出生地点使用独立的随机数，走法不改变外部条件。
"""

import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from .mechanisms import configured, validate_view
from .mechanisms.prospective import normalize
from .world import World


@dataclass(frozen=True)
class DeliverMessage:
    person: int
    message: str


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
    reference: dict | None = None  # 公开的指称表达，不含正确对象


class Game:
    """一局采办。所有推进都经 start / step；say 和 observe 只通知发生的事。"""

    def __init__(self, cfg: dict, say=None, observe=None, mechanisms=None):
        self.cfg, g, self.slots = cfg, cfg["game"], cfg["view"]["slots"]
        for key, minimum in (("lives", 1), ("life", 1), ("gap", 0)):
            if type(g[key]) is not int or g[key] < minimum:
                raise ValueError("lives/life must be positive integers; gap must be a nonnegative integer")
        self.world = World(g["seed"], {s["name"]: s["values"] for s in self.slots}, **cfg["world"])
        self.visible = [s["name"] for s in self.slots if s["visible"]]
        self.hidden = [s["name"] for s in self.slots if not s["visible"]]
        self.say = say or (lambda kind, **kw: None)
        self.observe = observe or (lambda day, p, seen: None)
        self.mechanisms = configured(cfg) if mechanisms is None else list(mechanisms)
        validate_view(cfg, self.mechanisms)
        self.phase: Literal["new", "go", "choose", "death", "done"] = "new"
        self.life, self.here = 0, None
        self.want, self.stalls = {}, {}
        self.log: list[bool] = []                               # 当前世已结算的每天；结束时加入 lives
        self.lives: list[list[bool]] = []                       # 已结束的每一世
        self.order_state, self.trades, self.audit = {}, [], []
        self.decision_interrupted, self.useful_news = False, 0

    def mechanism(self, name):
        return next((m for m in self.mechanisms if m.name == name), None)

    def notify(self, hook, *args):
        for mechanism in self.mechanisms:
            getattr(mechanism, hook)(self, *args)

    def record(self, kind, **fields):
        """私有、追加式事实记录；不会经 say/View 发给玩家。"""
        self.audit.append(deepcopy({"kind": kind, "day": self.world.day, "life": self.life, **fields}))

    def advance(self):
        self.world.step()
        self.notify("tick")

    def mechanism_truth(self):
        return {"order": deepcopy(self.order_state),
                "states": {m.name: m.snapshot() for m in self.mechanisms if m.name} if self.phase != "new" else {}}

    def mechanism_scores(self):
        task = self.mechanism("prospective")
        return {"prospective": task.metrics()} if task and self.phase != "new" else {}

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
                   {p: dict(seen) for p, seen in self.stalls.items()}, deepcopy(self.order_state.get("reference")))

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
        self.notify("reset")
        self._begin_life()
        return self.ask

    def step(self, answer: int | None | DeliverMessage) -> Ask | None:
        """回答当前阶段；非法节点在推进前拒绝，不消耗游戏日。"""
        self.decision_interrupted = False
        if isinstance(answer, DeliverMessage):
            mechanism = self.mechanism("prospective")
            if self.phase not in ("go", "choose") or mechanism is None:
                raise ValueError("当前不能传话")
            if type(answer.person) is not int or answer.person not in self.stalls:
                raise ValueError("只能向当前村里的人传话")
            if not isinstance(answer.message, str) or not normalize(answer.message):
                raise ValueError("口信不能为空")
            mechanism.deliver(self, answer.person, answer.message)
        elif self.phase == "go":
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
        self.advance()                                        # 第一日；之后只在逐日结算和死后空转时推进
        self.notify("life_start")
        self._order()

    def _look(self):
        self.stalls = {p: {s: self.world.value(p, s) for s in self.visible} for p in self.world.residents[self.here]}
        for p, seen in self.stalls.items():
            self.observe(self.world.day, p, seen)

    def _order(self):
        self.phase = "go"
        self.want = self.order_at(self.world.day)
        self.order_state = {"id": f"order:{self.world.day}", "issued_day": self.world.day,
                            "version": 1, "target": None, "reference": None, "hops": 0, "versions": []}
        self.useful_news = 0
        self._look()
        for m in self.mechanisms:
            self.want = m.order(self, self.want)
        self.order_state["versions"].append({"version": 1, "day": self.world.day, "want": dict(self.want)})
        if self.order_state["reference"]:
            self.say("reference_order", day=self.world.day, village=self.here,
                     reference=self.order_state["reference"], want=dict(self.want))
        else:
            self.say("order", day=self.world.day, village=self.here, **self.want)
        if self.mechanisms:
            self.record("order_issued", **self.order_state)
        self.say("stalls", stalls=self.stalls)
        for m in self.mechanisms:
            m.news(self)

    def _go(self, dest):
        if dest != self.here:
            self.notify("depart")
            days = self.world.distance(self.here, dest)
            self.say("travel" if days else "walk", village=dest, days=days)
            for _ in range(days):
                if not self._settle_day("road"):
                    return                                   # 最后一天还在路上：不到达，也不再推进一天
            self.here = dest
            self._look()
            self.say("stalls", stalls=self.stalls)
        self.phase = "choose"
        self.notify("arrive")

    def _choose(self, person):
        for mechanism in self.mechanisms:
            if mechanism.before_choice(self, person):
                return
        if self.mechanisms:
            self.record("choice", order_id=self.order_state["id"], version=self.order_state["version"],
                        person=person, target=self.order_state["target"], want=dict(self.want),
                        actual={s: self.world.value(person, s) for s in self.want} if person is not None else None)
        if person is None or any(self.stalls[person][s] != self.want[s] for s in self.visible):
            alive = self._settle_day("skip")
        else:
            success = all(self.world.value(person, s) == v for s, v in self.want.items())
            wrong_person = self.order_state["target"] is not None and person != self.order_state["target"]
            alive = self._settle_day("done" if success and not wrong_person else "fail", person, wrong_person)
        if alive:
            self._order()

    def _settle_day(self, outcome: Literal["road", "skip", "done", "fail"], person=None, wrong_person=False) -> bool:
        """结算一天，再进入下一游戏日或死亡边界；返回是否仍活着。"""
        self.log.append(outcome == "done")
        if outcome in ("done", "fail"):
            seen = {s: self.world.value(person, s) for s in self.hidden}
            self.observe(self.world.day, person, seen)
            if wrong_person:
                self.say("wrong_person", person=person, goods={s: self.want[s] for s in self.visible}, traits=seen)
            else:
                self.say(outcome, person=person, **(self.want | seen))
            self.trades.append({"day": self.world.day, "person": person,
                                "goods": {s: self.want[s] for s in self.visible}, "outcome": outcome})
        elif outcome == "skip":
            self.say("skip")
        if self.mechanisms:
            self.record("settlement", order_id=self.order_state["id"], version=self.order_state["version"],
                        outcome=outcome, person=person, wrong_person=wrong_person)
        self.notify("settled", outcome, person)
        g = self.cfg["game"]
        if len(self.log) == g["life"]:
            self.lives.append(self.log)
            self.phase = "death"
            self.say("death", gap=g["gap"])
            self.notify("life_end")
            if self.life == g["lives"]:
                self._afterlife()
            return False
        self.advance()
        return True

    def _afterlife(self):
        for _ in range(self.cfg["game"]["gap"]):
            self.advance()
        if self.life == self.cfg["game"]["lives"]:
            self.phase = "done"
            self.notify("finish")
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


def play(cfg: dict, make_agent, say=None, mechanisms=None) -> list[list[bool]]:
    """新建一局，让 make_agent(world, visible) 通过 go / choose / observe 玩完。"""
    return Game(cfg, say=say, mechanisms=mechanisms).play(make_agent)
