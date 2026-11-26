"""东家改主意：一次抵达、一次购买前检查；每个时点只抽一次，传话和重绘不会重抽。
指称订单改口时就不再点名（那个人只卖原来那样货），改成找任一符合要求的人。"""

from . import Mechanism, integer, probability


class Revisions(Mechanism):
    name = "revisions"

    def __init__(self, rate=0.1, max_revisions=2):
        self.rate = probability(rate, "revisions.rate")
        self.max_revisions = integer(max_revisions, "revisions.max_revisions", 0, 2)

    def reset(self, game):
        self.checked, self.count = set(), 0

    def order(self, game):
        self.checked = set()

    def on(self, game, kind, **kw):
        if kind == "arrive":
            self.revise(game, "arrive")

    def before_choice(self, game, person):
        return self.revise(game, "before_choice")

    def revise(self, game, stage):
        if stage in self.checked:
            return False
        self.checked.add(stage)
        order = game.order
        if order.version - 1 >= self.max_revisions:
            return False
        rng = self.rng(game, order.issued_day, stage)
        alternatives = [(s, v) for s in game.visible for v in game.world.slots[s] if v != order.want[s]
                        and any(game.world.value(p, s) == v for p in game.stalls)]
        if rng.random() >= self.rate or not alternatives:
            return False
        slot, value = rng.choice(alternatives)
        before, reference = dict(order.want), order.reference
        order.want[slot] = value
        order.target, order.reference, order.hops = None, None, 0
        order.version += 1
        order.versions.append({"version": order.version, "day": game.world.day, "want": dict(order.want)})
        self.count += 1
        game.record("revision", order_id=order.id, version=order.version, before=before,
                    after=dict(order.want), dropped_reference=reference, stage=stage)
        game.emit("revision_unref" if reference else "revision_open", slot=slot, old=before[slot], new=value,
                  reference=reference, want=dict(order.want))
        return True

    def snapshot(self):
        return {"count": self.count}
