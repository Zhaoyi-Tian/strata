"""文本环境：让 LLM（或任何读文字、写动作的 agent）来玩采办。规则和 play() 是同一份（Game.run），只是换成一问一答。

    from strata import Env, load
    env = Env(load(), seed=0)
    env.instructions                      # 常驻说明：开场白、地图、动作格式。放进 system prompt，不算要记的东西
    obs = env.reset()                     # 第一天：订单、本村的摊子，问你今天怎么办
    obs, done, info = env.step("找 老秦")  # 结果，以及第二天的订单和摊子

每天一到两问：
  先问「今天怎么办」：找 <人名>、不做（都是留在本村做）、去 <村名>、留下。
  去了别村，或说了「留下」，再问一次「找谁」：找 <人名>、不做。
一世到头时 env.life_ended 为真，这一问回什么都行（runner 直接回「继续」）；失忆协议就在这时写遗书、清空上下文。
最后一世到头就是 done，没有这一问。
看不懂的动作不消耗天数，提示后原样再问，info["parse_ok"] 为假。
env.truth() 是此刻的真值，只给评测、归因和全知用，绝不能进 agent 的上下文。

自己在终端里打字玩（Windows 也行）：python -m strata.env [--config 文件] [--seed N]
"""

import argparse
import re

from .config import load
from .game import Ask, Game
from .view import View

LAYERS = ("地区", "村", "人")

ACTIONS = """每一步只回一个动作，不要写别的：
  找 <人名>   找这个人做今天这单
  不做        今天这单不做
  去 <村名>   去别的村，到了再决定找谁
  留下        待在这个村，再决定找谁"""

PROMPT = {
    "go": "今天怎么办？（找 <人名> / 不做 / 去 <村名> / 留下）",
    "choose": "找谁？（找 <人名> / 不做）",
    "death": "（这一世结束了。回任意内容，进入下一世。）",
}

_TAIL = re.compile(r"[\s。．.！!，,；;]+$")
_ACTION = re.compile(r"(找|去)\s*(\S+)|留下|不做")


class Env:
    def __init__(self, cfg: dict | None = None, seed: int | None = None, mechanisms=()):
        """cfg 是 strata.load() 读出来的配置；seed 不给就用配置里的。mechanisms 见 strata.mechanisms。
        一个 Env 玩一局；再调 reset() 会从头再来（同一个 seed，同一个世界）。"""
        cfg = cfg or load()
        if seed is not None:
            cfg = {**cfg, "game": {**cfg["game"], "seed": seed}}
        self.cfg, self.mechanisms = cfg, list(mechanisms)
        self._build()

    def _build(self):
        self.view = View(self.cfg["view"])
        self.game = Game(self.cfg, say=self._say, mechanisms=self.mechanisms)
        w = self.game.world
        self._regions = [n for n in range(len(w.depth)) if w.depth[n] == 0]
        self._village_by_name = {self.name(v): v for v in w.villages}
        self._steps, self.ask, self.done = None, None, False
        self._lines, self._events = [], []

    # ---- 给 agent 的 ----

    @property
    def instructions(self) -> str:
        """常驻说明：开场白、地图、动作格式。整局不变。"""
        return "\n\n".join([self.cfg["view"]["intro"], self.view.map(self.cfg["world"]["size"]), ACTIONS])

    def reset(self) -> str:
        """开局，返回第一天的观察。"""
        if self._steps is not None:
            self._build()
        self._steps = self.game.run()
        self._lines, self._events = [], []
        self._send(None, first=True)
        return self._obs()

    def step(self, action: str) -> tuple[str, bool, dict]:
        """回一个动作，返回 (观察, 是否整局结束, info)。"""
        if self._steps is None:
            raise RuntimeError("先调 reset()")
        if self.done:
            raise RuntimeError("这一局已经结束了")
        kind = self.ask.kind
        answers, error = self._parse(action)
        if error:
            return f"{error}\n{PROMPT[kind]}", False, self._info(action, kind, error)
        self._lines, self._events = [], []
        for a in answers:                                       # 「找 X」在「今天怎么办」时 = 留下 + 找 X
            self._send(a)
        return self._obs(), self.done, self._info(action, kind)

    def legal_actions(self) -> list[str]:
        """此刻能回的所有动作。可以给 agent 看，也可以不给（看实验设置）。"""
        if self.done:
            return []
        if self.ask.kind == "death":
            return ["继续"]
        people = [f"找 {self.name(p)}" for p in self.ask.stalls] + ["不做"]
        if self.ask.kind == "choose":
            return people
        return people + [f"去 {self.name(v)}" for v in self.game.world.villages if v != self.ask.here] + ["留下"]

    @property
    def life_ended(self) -> bool:
        """一世刚到头、下一世还没开始。失忆协议在这时写遗书。"""
        return not self.done and self.ask.kind == "death"

    # ---- 给评测的 ----

    @property
    def world(self):
        return self.game.world

    @property
    def lives(self) -> list[list[bool]]:
        """已经过完的每一世，每天成没成单。"""
        return self.game.lives

    def name(self, n) -> str | None:
        """节点 n（world 里的编号）在文字里叫什么。agent 还没见过的人没有名字，返回 None。"""
        w = self.game.world
        if w.depth[n] == 0:
            return self.view.name("region", self._regions.index(n))
        if w.depth[n] == 1:
            return self.view.name("village", w.villages.index(n))
        return self.view.names["person"].get(n)

    def truth(self) -> dict:
        """此刻的真值。nodes 按编号，每个节点：名字、在哪一层、上一层是谁；每个槽位上
        value（表现出来的值）、own（是不是自己的值）、source / source_layer（由哪个节点、哪一层决定）、since（上次变是哪天）。"""
        w, g = self.game.world, self.game

        def slot(n, s):
            src = w.source(n, s)
            return {"value": w.value(n, s), "own": src == n, "source": src, "source_layer": LAYERS[w.depth[src]],
                    "since": w.since[s][n]}

        return {
            "day": w.day, "life": g.life, "day_in_life": len(g.log), "here": g.here, "want": dict(g.want),
            "nodes": {n: {"name": self.name(n), "layer": LAYERS[w.depth[n]], "parent": w.parent[n],
                          **{s: slot(n, s) for s in w.slots}} for n in range(len(w.depth))},
        }

    # ---- 内部 ----

    def _say(self, kind, **kw):
        event = {"kind": kind, **kw}
        if "village" in event:
            event["village"] = self.game.world.villages[event["village"]]   # 统一成节点编号
        self._events.append(event)
        self._lines.append(self.view.say(kind, **kw))

    def _send(self, answer, first=False):
        try:
            self.ask = next(self._steps) if first else self._steps.send(answer)
        except StopIteration:
            self.ask, self.done = None, True

    def _obs(self) -> str:
        return "\n".join(self._lines + ([] if self.done else [PROMPT[self.ask.kind]]))

    def _parse(self, action: str) -> tuple[list, str | None]:
        """把动作翻成要送给 Game 的一两个主意；看不懂就返回提示。"""
        ask: Ask = self.ask
        if ask.kind == "death":
            return [None], None
        text = _TAIL.sub("", str(action).strip()).strip("「」“”\"'` ")
        m = _ACTION.fullmatch(text)
        if not m:
            return [], f"看不懂这个动作：「{str(action).strip()}」。"
        verb, target = (m.group(1), m.group(2)) if m.group(1) else (text, None)
        here = ask.here
        stay = [here] if ask.kind == "go" else []
        if verb == "找":
            p = next((p for p in ask.stalls if self.name(p) == target), None)
            if p is None:
                return [], f"{self.name(here)}没有叫「{target}」的人。"
            return stay + [p], None
        if verb == "不做":
            return stay + [None], None
        if ask.kind == "choose":
            return [], "今天已经定在这个村了，只能在这里找人，或者不做。"
        if verb == "留下":
            return [here], None
        v = self._village_by_name.get(target)
        if v is None:
            return [], f"没有叫「{target}」的村子。"
        return [v], None

    def _info(self, action, asked, error=None) -> dict:
        g = self.game
        return {
            "life": g.life, "day": g.world.day, "day_in_life": len(g.log),
            "asked": asked,                                       # 这一步回答的是哪一问
            "phase": "done" if self.done else self.ask.kind,      # 下一问
            "action": action, "parse_ok": error is None, "error": error,
            "life_ended": any(e["kind"] == "death" for e in self._events) if error is None else False,
            "events": [] if error else self._events,              # 这一步发生的事；村和人都是节点编号
        }


def main():
    ap = argparse.ArgumentParser(prog="python -m strata.env", description="在终端里打字玩文本版。")
    ap.add_argument("--config")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    env = Env(load(a.config), seed=a.seed)
    print(env.instructions, "", env.reset(), sep="\n")
    while not env.done:
        try:
            action = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n不玩了。")
            return
        print(env.step(action)[0])
    print("\n每一世做成几单：" + "，".join(f"第 {i} 世 {sum(log)}/{len(log)}" for i, log in enumerate(env.lives, 1)))


if __name__ == "__main__":
    main()
