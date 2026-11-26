"""Part A 的机制：传闻、指称订单、改主意、前瞻任务、干扰信息。每项可在 [mechanisms] 里单独打开。

一个机制是一个对象，挂到 Game / Env / play 的 mechanisms=[...] 上（None 按配置装配，[] 全关）。它只有五个时刻：

  reset(game)                    每局开场，清空自己的状态。
  order(game)                    今天的订单刚生成、还没说出来；可以改 game.order（指称订单）。
  on(game, kind, **kw)           Game 发生的每件事：公开事件（order、stalls、done、travel、rumor……），
                                 以及只发给机制的时刻 tick（世界过了一天，含路上和死后）、news（订单和摊子说完）、
                                 arrive / depart（到达 / 离开一个村）、settled（一天结算完）、
                                 life_start / life_end / finish。
  before_choice(game, person)    要买之前；返回 True 就先不买，把新消息给玩家看，再让他重选（改主意）。
  snapshot()                     只给评测看的状态。

约定：
  机制要说话就用 game.emit(种类, ...)，别的机制也听得到；新的种类要在世界观的 [lines] 里加一行台词。
  改了订单（比如改口）要把 game.order.version 加一：Env 靠它知道该停下来，先把新口信给玩家看。
  同一时刻各机制按列表顺序被调用；Distraction 要排在最后，才数得到当天全部有用消息（configured 已这样排）。
  要私下记一笔就用 game.record(种类, ...)，只进评测审计，不给玩家。不要把答案放进公开事件。
  要随机数就用 self.rng(game, 日期, ...)，按日取、不要动 world.rng，走法不同也不会让后面的随机数错位。
  村和人都用世界节点编号，由 View 起名字。
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

    def order(self, game):
        pass

    def on(self, game, kind, **kw):
        pass

    def before_choice(self, game, person) -> bool:
        return False

    def snapshot(self):
        return {}


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
        "revisions": ("revision_open", "revision_unref", "reference_transaction", "reference_previous"),
        "prospective": ("commission", "message_delivered"),
        "distraction": ("chatter",),
    }
    view = cfg["view"]
    slots = [s["name"] for s in view["slots"]]
    for mechanism in mechanisms:
        if mechanism.name == "rumor" and not getattr(mechanism, "all_truthful", True) \
                and getattr(mechanism, "credibility_slot", None) not in slots:
            raise ValueError("rumor.credibility_slot must name an existing slot")
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
