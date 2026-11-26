"""干扰信息：只改变消息量，不改世界和任务。useful_ratio 是当天有用消息占全部消息的目标比例，数量仍受上限约束。"""

import math

from . import Mechanism, integer, probability

USEFUL = {"reference_order", "rumor", "commission", "revision_open", "revision_unref"}


class Distraction(Mechanism):
    name = "distraction"

    def __init__(self, useful_ratio=0.5, max_per_news=2):
        self.useful_ratio = probability(useful_ratio, "distraction.useful_ratio")
        self.max_per_news = integer(max_per_news, "distraction.max_per_news")

    def reset(self, game):
        self.count, self.useful = 0, 0

    def on(self, game, kind, **kw):
        if kind in ("order", "reference_order"):
            self.useful = 0
        if kind in USEFUL:
            self.useful += 1
        if kind == "news":
            self.news(game)

    def news(self, game):
        q = self.useful_ratio
        count = self.max_per_news if q == 0 else math.ceil(self.useful * (1 - q) / q)
        if self.useful == 0 and q < 1:
            count = max(count, 1)
        count = min(count, self.max_per_news)
        rng = self.rng(game, game.world.day, "news")
        choices = list(game.cfg["view"]["mechanism_text"]["chatter"])
        rng.shuffle(choices)
        for message in choices[:count]:
            speaker = rng.choice(game.world.residents[game.here])
            game.emit("chatter", speaker=speaker, message=message)
            game.record("distraction", speaker=speaker, message=message)
            self.count += 1

    def snapshot(self):
        return {"count": self.count}
