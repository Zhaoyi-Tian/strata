"""指称只引用玩家听到过的交易/订单；公开表述与正确对象分开保存。"""

from copy import deepcopy

from . import Mechanism, integer, probability


class ReferenceOrders(Mechanism):
    name = "reference_orders"

    def __init__(self, rate=0.2, max_hops=2):
        self.rate = probability(rate, "reference_orders.rate")
        self.max_hops = integer(max_hops, "reference_orders.max_hops", 1, 2)

    def reset(self, game):
        self.orders = []

    def order(self, game):
        rng, want = self.rng(game, game.world.day, "order"), game.want
        if rng.random() >= self.rate or not game.visible:
            return
        w, slot = game.world, game.visible[0]

        def fits(person):
            return all(w.value(person, s) == want[s] for s in game.visible)

        candidates = [
            {"target": t["person"], "hops": 1,
             "public": {"kind": "transaction", "day": t["day"], "slot": slot, "value": t["goods"][slot]}}
            for t in game.trades if fits(t["person"])
        ]
        candidates += [
            {"target": o["target"], "hops": o["hops"] + 1,
             "public": {"kind": "order", "day": o["day"]}, "antecedent_order": o["id"]}
            for o in self.orders if o["hops"] < self.max_hops and not o.get("revoked") and fits(o["target"])
        ]
        if not candidates:
            return
        chosen = deepcopy(rng.choice(candidates))
        game.order.target, game.order.reference, game.order.hops = chosen["target"], chosen["public"], chosen["hops"]
        entry = {"id": game.order.id, "day": w.day, **chosen}
        self.orders.append(entry)
        game.record("reference_order", **entry)

    def on(self, game, kind, **kw):
        if kind == "revision_unref":                       # 东家说了不必再找那人，以后也不能再顺着这单指过去
            for entry in self.orders:
                if entry["id"] == game.order.id:
                    entry["revoked"] = True

    def snapshot(self):
        return {"count": len(self.orders), "last": deepcopy(self.orders[-1]) if self.orders else None}
