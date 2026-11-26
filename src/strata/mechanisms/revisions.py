"""一次抵达、一次购买前检查；每个时点只抽一次，传话和重绘不会重抽。"""

from . import Mechanism, integer, probability


class Revisions(Mechanism):
    name = "revisions"

    def __init__(self, rate=0.1, max_revisions=2):
        self.rate = probability(rate, "revisions.rate")
        self.max_revisions = integer(max_revisions, "revisions.max_revisions", 0, 2)

    def reset(self, game):
        self.checked, self.count = set(), 0

    def order(self, game, want):
        self.checked = set()
        return want

    def revise(self, game, stage):
        if stage in self.checked:
            return False
        self.checked.add(stage)
        state = game.order_state
        if state["version"] - 1 >= self.max_revisions:
            return False
        rng = self.rng(game, state["issued_day"], stage)
        people = [state["target"]] if state["target"] is not None else list(game.stalls)
        alternatives = [(s, v) for s in game.visible for v in game.world.slots[s] if v != game.want[s]
                        and any(game.world.value(p, s) == v for p in people)]
        if rng.random() >= self.rate or not alternatives:
            return False
        slot, value = rng.choice(alternatives)
        before = dict(game.want)
        game.want[slot] = value
        state["version"] += 1
        state["versions"].append({"version": state["version"], "day": game.world.day, "want": dict(game.want)})
        self.count += 1
        game.record("revision", order_id=state["id"], version=state["version"], before=before,
                    after=dict(game.want), target=state["target"], stage=stage)
        game.say("revision", slot=slot, old=before[slot], new=game.want[slot],
                 reference=state["reference"], want=dict(game.want))
        game.decision_interrupted = True
        return True

    def arrive(self, game):
        self.revise(game, "arrive")

    def before_choice(self, game, person):
        return self.revise(game, "before_choice")

    def snapshot(self):
        return {"count": self.count}
