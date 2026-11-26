"""新机制（玩法 A）挂在这里：传闻、指称订单、改主意、前瞻任务、干扰信息……

每个机制是一个对象，挂到 Game(mechanisms=[...])、play(..., mechanisms=[...]) 或 Env(..., mechanisms=[...]) 上。
Game 保留两个原有挂钩：

  order(game, want) -> want   订单刚生成、还没说出来。可以改订单（指称订单、改主意、前瞻任务）。
  news(game)                  当天的订单和摊子说完、拿主意之前。可以用 game.say(种类, ...) 加几句话
                              （传闻、干扰信息）；新的种类要在世界观的 [lines] 里加一行台词。

能用到的状态：game.world（真值，机制可以看）、game.here、game.want、game.life、game.log、game.say。

约定：
  机制要用随机数就自己开一个，比如 random.Random(f"{seed}:rumor")，不要动 world.rng。
  基础订单由 game.order_at(day) 按世界日固定，出生地点由 seed 和世数固定。机制改订单时也应按日取随机数，
  避免不同走法调用次数不同，导致后续订单错位。
  reset 在每局开场清空状态；tick 在每次世界日推进后调用，包括路途和死后空转。
  life_start / life_end / finish 通知生命周期；arrive 在留村或抵达后、交易前调用，depart 在离开前调用。
  before_choice 返回 True 时暂停本次购买，先展示新消息，再让玩家重新选择。
  settled 在每日结算后、推进世界前调用；snapshot 只供评测。
  game.record 追加私有审计；game.say 仅发送公开事件。不要把答案放进公开事件。
  村和人都用世界节点编号；game.say 的 village / person 字段也遵守这一约定，由 View 起名字。
"""


import math
import random


def probability(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer >= {minimum}" + (f" and <= {maximum}" if maximum is not None else ""))
    return value


class Mechanism:
    """什么都不做的机制，新机制继承它，只改用得到的那个时刻。"""

    name = ""

    def rng(self, game, *identity):
        return random.Random(":".join(map(str, (game.cfg["game"]["seed"], self.name, *identity))))

    def reset(self, game):
        pass

    def tick(self, game):
        pass

    def life_start(self, game):
        pass

    def life_end(self, game):
        pass

    def finish(self, game):
        pass

    def arrive(self, game):
        pass

    def depart(self, game):
        pass

    def before_choice(self, game, person) -> bool:
        return False

    def settled(self, game, outcome, person):
        pass

    def snapshot(self):
        return {}

    def order(self, game, want: dict) -> dict:
        return want

    def news(self, game) -> None:
        pass


def configured(cfg):
    """固定装配顺序；每项独立构造，未启用的项不消耗随机数。"""
    from .distraction import Distraction
    from .prospective import Prospective
    from .reference_orders import ReferenceOrders
    from .revisions import Revisions
    from .rumor import Rumor

    classes = (ReferenceOrders, Rumor, Prospective, Revisions, Distraction)
    settings = cfg.get("mechanisms", {})
    if not isinstance(settings, dict) or set(settings) - {cls.name for cls in classes}:
        raise ValueError("unknown mechanism configuration")
    result = []
    for cls in classes:
        entry = settings.get(cls.name, {})
        if not isinstance(entry, dict):
            raise ValueError(f"{cls.name} must be a table")
        options = dict(entry)
        enabled = options.pop("enabled", False)
        if type(enabled) is not bool:
            raise ValueError(f"{cls.name}.enabled must be a boolean")
        if enabled:
            try:
                result.append(cls(**options))
            except TypeError as error:
                raise ValueError(f"invalid {cls.name} configuration: {error}") from error
    return result


def validate_view(cfg, mechanisms):
    """旧世界观可继续全关运行；启用机制时明确报告缺失的呈现字段。"""
    required = {
        "rumor": ("rumor",),
        "reference_orders": ("reference_order", "reference_transaction", "reference_previous", "wrong_person"),
        "revisions": ("revision", "revision_open", "reference_transaction", "reference_previous"),
        "prospective": ("commission", "message_delivered"),
        "distraction": ("chatter",),
    }
    view = cfg["view"]
    for mechanism in mechanisms:
        for key in required.get(mechanism.name, ()):
            if not isinstance(view["lines"].get(key), str):
                raise ValueError(f"worldview missing lines.{key}")
        collection = {"prospective": "messages", "distraction": "chatter"}.get(mechanism.name)
        if collection:
            values = view.get("mechanism_text", {}).get(collection)
            if not isinstance(values, list) or not values or not all(isinstance(s, str) and s.strip() for s in values):
                raise ValueError(f"worldview needs nonempty mechanism_text.{collection}")
            if collection == "messages":
                from .prospective import normalize
                if not all(normalize(s) for s in values):
                    raise ValueError("mechanism_text.messages must contain words, not just punctuation")


__all__ = ["Mechanism", "configured"]
