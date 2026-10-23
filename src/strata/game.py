"""采办这一局。

每天：在昨天落脚的村子醒来，看见本村每个人的可见特质；接一单（可见的特质随便要一样，隐藏的总是要第一个值，
例如「找一个卖铁、守信的人」）；留下或去别村（同一地区当天就到，别的地区走一天）；挑一个人做这单（也可以不做），
各方面都对上就成了，做完才知道他的隐藏特质；挑了不卖这样货的人，就等于不做。
一世活满就死，世间空转一段时间，带着全部记忆在随便哪个村重生。
世界和订单各用独立的随机数，所以所有采办面对的是同一个世界、同一串订单。

规则只写一遍，在 Game.run() 里：它是个生成器，每到要拿主意的时候就 yield 一个 Ask，等外面 send() 回主意。
  play()           回调式，给规则采办用（agent.go / choose / observe），和以前一样。
  strata.env.Env   文本式，给 LLM 用（env.step("找 老秦")）。
两边走的是同一份规则，所以换了接口，分数也不会变。"""

import random
from dataclasses import dataclass, field

from .world import World


@dataclass
class Ask:
    """一个要拿主意的时刻。
    go：     去哪。回一个村（回 here 就是留下）。
    choose： 找谁。回 stalls 里的一个人，或 None（不做）。
    death：  一世到头、下一世开始之前（最后一世没有这一问）。回什么都行；失忆协议在这时写遗书。"""

    kind: str
    day: int
    here: int
    want: dict = field(default_factory=dict)
    stalls: dict = field(default_factory=dict)


class Game:
    """一局采办的全部状态。say(种类, **字段) 把发生的事写成文字；observe(天, 人, 见闻) 告诉旁听者看见了什么；
    mechanisms 是挂上来的新机制（见 strata.mechanisms）。"""

    def __init__(self, cfg: dict, say=None, observe=None, mechanisms=()):
        self.cfg, g, self.slots = cfg, cfg["game"], cfg["view"]["slots"]
        self.world = World(g["seed"], {s["name"]: s["values"] for s in self.slots}, **cfg["world"])
        self.visible = [s["name"] for s in self.slots if s["visible"]]
        self.hidden = [s["name"] for s in self.slots if not s["visible"]]
        self.orders = random.Random(f"{g['seed']}:orders")
        self.say = say or (lambda kind, **kw: None)
        self.observe = observe or (lambda day, p, seen: None)
        self.mechanisms = list(mechanisms)
        self.lives: list[list[bool]] = []                     # 每一世每天成没成单（在路上的那天算没成）
        self.life, self.log, self.here, self.want = 0, [], None, {}

    def look(self, village) -> dict:
        stalls = {p: {s: self.world.value(p, s) for s in self.visible} for p in self.world.residents[village]}
        for p, seen in stalls.items():
            self.observe(self.world.day, p, seen)
        return stalls

    def run(self):
        """一整局。yield Ask，等 send(主意)；玩完 return 每一世每天成没成单。"""
        g, world = self.cfg["game"], self.world
        for life in range(1, g["lives"] + 1):
            self.life = life
            if life > 1:
                self.say("rebirth", life=life)
            here, log = self.orders.choice(world.villages), []
            self.here, self.log = here, log
            while len(log) < g["life"]:
                world.step()
                stalls = self.look(here)
                want = {s["name"]: self.orders.choice(s["values"]) if s["visible"] else s["values"][0] for s in self.slots}
                for m in self.mechanisms:
                    want = m.order(self, want)
                self.want = want
                self.say("order", day=world.day, village=world.villages.index(here), **want)
                self.say("stalls", stalls=stalls)
                for m in self.mechanisms:
                    m.news(self)
                dest = yield Ask("go", world.day, here, want, stalls)
                if dest != here:
                    days = world.distance(here, dest)
                    self.say("travel" if days else "walk", village=world.villages.index(dest), days=days)
                    for _ in range(days):
                        world.step()
                    log += [False] * days
                    here = self.here = dest
                    if len(log) >= g["life"]:
                        break
                    stalls = self.look(here)
                    self.say("stalls", stalls=stalls)
                p = yield Ask("choose", world.day, here, want, stalls)
                if p is not None and any(stalls[p][s] != want[s] for s in self.visible):
                    p = None                                    # 他不卖你要的货，这单做不了，也就打听不到什么
                if p is None:
                    log.append(False)
                    self.say("skip")
                    continue
                log.append(all(world.value(p, s) == v for s, v in want.items()))
                seen = {s: world.value(p, s) for s in self.hidden}
                self.observe(world.day, p, seen)
                self.say("done" if log[-1] else "fail", person=p, **(want | seen))
            self.lives.append(log[:g["life"]])
            self.say("death", gap=g["gap"])
            if life < g["lives"]:
                yield Ask("death", world.day, here)
            for _ in range(g["gap"]):
                world.step()
        return self.lives


def play(cfg: dict, make_agent, say=None, mechanisms=()) -> list[list]:
    """回调式地玩一局：make_agent(world, visible) 造一个采办，世界每天问它 go、choose，把见闻告诉它的 observe。
    返回每一世每天成没成单（在路上的那天算没成）。"""
    game = Game(cfg, say, mechanisms=mechanisms)
    agent = make_agent(game.world, game.visible)
    game.observe = agent.observe
    steps = game.run()
    try:
        ask = next(steps)
        while True:
            if ask.kind == "go":
                ask = steps.send(agent.go(ask.day, ask.here, ask.want, ask.stalls))
            elif ask.kind == "choose":
                ask = steps.send(agent.choose(ask.day, ask.want, ask.stalls))
            else:
                ask = steps.send(None)
    except StopIteration as end:
        return end.value
