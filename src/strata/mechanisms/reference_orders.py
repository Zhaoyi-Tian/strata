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

    def order(self, game, want):
        rng = self.rng(game, game.world.day, "order")
        if rng.random() >= self.rate or not game.visible:
            return want
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
            for o in self.orders if o["hops"] < self.max_hops and fits(o["target"])
        ]
        if not candidates:
            return want
        chosen = deepcopy(rng.choice(candidates))
        game.order_state.update(target=chosen["target"], reference=chosen["public"], hops=chosen["hops"])
        entry = {"id": game.order_state["id"], "day": w.day, **chosen}
        self.orders.append(entry)
        game.record("reference_order", **entry)
        return want

    def snapshot(self):
        return {"count": len(self.orders), "last": deepcopy(self.orders[-1]) if self.orders else None}
