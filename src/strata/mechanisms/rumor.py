"""有来源、有历史日期的传闻；历史快照有界，审计保存每次引用的事实。"""

from collections import deque
from copy import deepcopy

from . import Mechanism, integer, probability


class Rumor(Mechanism):
    name = "rumor"

    def __init__(self, rate=0.5, min_delay=0, max_delay=5, all_truthful=False, credibility_slot="守不守信"):
        self.rate = probability(rate, "rumor.rate")
        self.min_delay = integer(min_delay, "rumor.min_delay")
        self.max_delay = integer(max_delay, "rumor.max_delay", self.min_delay)
        if type(all_truthful) is not bool:
            raise ValueError("rumor.all_truthful must be a boolean")
        self.all_truthful, self.credibility_slot = all_truthful, credibility_slot

    def reset(self, game):
        self.history = deque(maxlen=self.max_delay + 1)
        self.last, self.count = None, 0
        self.remember(game)

    def on(self, game, kind, **kw):
        if kind == "tick":
            self.remember(game)
        elif kind == "news":
            self.news(game)

    def remember(self, game):
        w = game.world
        self.history.append((w.day, {
            (p, s): {"value": w.value(p, s), "source": w.source(p, s), "since": w.since[s][p]}
            for p in w.people for s in game.hidden
        }))

    def news(self, game):
        w = game.world
        rng = self.rng(game, w.day, "news")
        if rng.random() >= self.rate or not game.hidden or len(w.people) < 2:
            return
        eligible = [(day, facts) for day, facts in self.history if self.min_delay <= w.day - day <= self.max_delay]
        if not eligible:
            return
        day, facts = rng.choice(eligible)
        speaker = rng.choice(w.residents[game.here])
        person = rng.choice([p for p in w.people if p != speaker])
        slot = rng.choice(game.hidden)
        fact = facts[person, slot]
        truthful = self.all_truthful or w.value(speaker, self.credibility_slot) == w.slots[self.credibility_slot][0]
        alternatives = [v for v in w.slots[slot] if v != fact["value"]]
        claimed = fact["value"] if truthful or not alternatives else rng.choice(alternatives)
        self.count += 1
        self.last = {"speaker": speaker, "person": person, "slot": slot, "statement_day": day,
                     "heard_day": w.day, "claimed_value": claimed, "historical": fact,
                     "fabricated": claimed != fact["value"], "current_value": w.value(person, slot),
                     "stale": fact["value"] != w.value(person, slot)}
        game.record("rumor", **self.last)
        game.emit("rumor", speaker=speaker, person=person, village=w.parent[person],
                  statement_day=day, slot=slot, value=claimed)

    def snapshot(self):
        return {"count": self.count, "last": deepcopy(self.last)}
