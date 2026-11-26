"""采办。每天在昨天的村子醒来，看见本村每个人的可见特质，接一单，决定留下还是去别村（go），
到了再看一眼摊子，挑一个人做这单（choose），做完才知道他的隐藏特质（observe）。
几种采办只差在「怎么根据记忆估计一个人此刻是什么样」（prob）；去哪、挑谁的规则都一样：
  去哪：每个村算「到了在对得上货的人里挑最可信的」成单的把握，再除以花的天数（路上 + 做单这一天），挑最大的；
  挑谁：眼前对得上货的人里最可信的；没人对得上就今天不做。
它们只知道谁住哪个村，不知道真值（全知除外，它是天花板）。"""

import random
from collections import Counter

from .hier import Hier


class Agent:
    name = ""

    def __init__(self, world, visible: list[str]):
        self.world, self.visible, self.rng = world, visible, random.Random(self.name)

    def prob(self, day, p, s, v) -> float:
        """凭记忆，p 此刻的槽位 s 是 v 的把握。"""
        return 1 / len(self.world.slots[s])

    def observe(self, day, p, seen: dict):
        pass

    def act(self, ask):
        """回答 Game 的一问：去哪、找谁；一世结束那一问不用回。"""
        if ask.kind == "go":
            return self.go(ask.day, ask.here, ask.want, ask.stalls)
        if ask.kind == "choose":
            return self.choose(ask.day, ask.want, ask.stalls)
        return None

    def fit(self, day, p, want, slots, stalls):
        """p 在这几个槽位上都对上的把握；眼前摊子上看得见的就不用猜。"""
        out = 1.0
        for s in slots:
            out *= stalls[p][s] == want[s] if s in stalls.get(p, ()) else self.prob(day, p, s, want[s])
        return out

    def hope(self, day, w, want, stalls):
        """去村 w 能成单的把握：到了一看，会在对得上货的人里挑最可信的那个。"""
        hidden = [s for s in want if s not in self.visible]
        trust = sorted(((self.fit(day, p, want, hidden, stalls), self.fit(day, p, want, self.visible, stalls))
                        for p in self.world.residents[w]), reverse=True)
        out, none_yet = 0.0, 1.0
        for t, v in trust:
            out += none_yet * v * t
            none_yet *= 1 - v
        return out

    def go(self, day, here, want, stalls):
        days = {w: 1 + self.world.distance(here, w) for w in self.world.villages}
        return max(days, key=lambda w: (self.hope(day, w, want, stalls) / days[w], -days[w], self.rng.random()))

    def choose(self, day, want, stalls):
        """挑一个人；谁都没指望（比如没人卖这样货）就不做。"""
        p = max(stalls, key=lambda p: (self.fit(day, p, want, want, stalls), self.rng.random()))
        return p if self.fit(day, p, want, want, stalls) > 0 else None


class Anyone(Agent):
    name = "随便找"


class Latest(Agent):
    name = "只信最新"

    def __init__(self, *a):
        super().__init__(*a)
        self.last = {}                                          # (人, 槽位) -> 最近一次看到的值

    def prob(self, day, p, s, v):
        seen = self.last.get((p, s))
        return super().prob(day, p, s, v) if seen is None else float(seen == v)

    def observe(self, day, p, seen):
        for s, v in seen.items():
            self.last[p, s] = v


class Majority(Agent):
    name = "只信多数"

    def __init__(self, *a):
        super().__init__(*a)
        self.counts = {}                                        # (人, 槽位) -> Counter

    def prob(self, day, p, s, v):
        c = self.counts.get((p, s))
        return super().prob(day, p, s, v) if not c else c[v] / c.total()

    def observe(self, day, p, seen):
        for s, v in seen.items():
            self.counts.setdefault((p, s), Counter())[v] += 1


class Inference(Agent):
    name = "分层推断"

    def __init__(self, *a):
        super().__init__(*a)
        self.hier = {s: Hier(self.world, s) for s in self.world.slots}

    def prob(self, day, p, s, v):
        return self.hier[s].dist(p, day)[v]

    def observe(self, day, p, seen):
        for s, v in seen.items():
            self.hier[s].observe(day, p, v)


class Oracle(Agent):
    name = "全知"

    def prob(self, day, p, s, v):
        return float(self.world.value(p, s) == v)


AGENTS = [Anyone, Latest, Majority, Inference, Oracle]
