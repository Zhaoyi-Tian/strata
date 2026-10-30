"""strata [--config 文件] [--seed N]：自己玩一局采办。

每天两件事：去哪、找谁，都用上下键选，回车定下。q 或 Ctrl-D 退出。"""

import argparse

from . import term
from .config import load
from .game import Game
from .view import View


class Player:
    """把每天的两个决定交给键盘。"""

    def __init__(self, world, view):
        self.world, self.view = world, view

    def place(self, v) -> tuple[str, str]:
        return self.view.name(v), self.view.name(self.world.parent[v])

    def go(self, day, here, want, stalls):
        near = sorted(self.world.villages, key=lambda v: (v != here, self.world.distance(here, v), v))
        options = []
        for v in near:
            name, region = self.place(v)
            days = self.world.distance(here, v)
            cost = "留下" if v == here else "当天到" if days == 0 else f"走 {days} 天"
            options.append(f"{name}  {term.paint(region + ' · ' + cost, 'dim')}")
        return near[term.menu("去哪", options)]

    def choose(self, day, want, stalls):
        people = list(stalls)
        options = [f"{self.view.name(p)}  " + "、".join(term.paint(v, "want") if want[s] == v else v
                                                                 for s, v in stalls[p].items()) for p in people]
        fits = [k for k, p in enumerate(people) if all(want[s] == v for s, v in stalls[p].items())]
        k = term.menu("找谁", [*options, "今天不做"], start=fits[0] if fits else len(people))
        return people[k] if k < len(people) else None

    def observe(self, day, p, seen):
        pass


def show(view, visible):
    """把发生的事打印出来：要的货标亮，成败上色，每天之间空一行。"""
    want = {}

    def say(kind, **kw):
        if kind == "order":
            want.clear()
            want.update({s: kw[s] for s in visible})
            kw |= {s: term.paint(kw[s], "want") for s in visible}
            print()
        if kind == "stalls":
            kw["stalls"] = {p: {s: term.paint(v, "want") if want.get(s) == v else v for s, v in seen.items()}
                            for p, seen in kw["stalls"].items()}
        style = {"done": "good", "fail": "bad", "skip": "dim", "walk": "road", "travel": "road",
                 "death": "fate", "rebirth": "fate"}.get(kind)
        line = view.say(kind, **kw)
        print(term.paint(line, style) if style else line)
    return say


def main():
    ap = argparse.ArgumentParser(prog="strata", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--seed", type=int, help="换一个世界")
    a = ap.parse_args()
    cfg = load(a.config)
    if a.seed is not None:
        cfg["game"]["seed"] = a.seed
    game = Game(cfg)
    view = View(cfg["view"], game.world)
    game.say = show(view, game.visible)

    print(cfg["view"]["intro"], "", view.map(), sep="\n")
    try:
        lives = game.play(lambda world, _: Player(world, view))
    except (EOFError, KeyboardInterrupt):
        print("\n不玩了。")
        return
    print("\n每一世做成几单：" + "，".join(f"第 {i} 世 {sum(log)}/{len(log)}" for i, log in enumerate(lives, 1)))


if __name__ == "__main__":
    main()
