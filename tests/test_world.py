import unittest
from unittest import mock

from strata import World, load, play
from strata.__main__ import main

CFG = load()
SLOTS = {s["name"]: s["values"] for s in CFG["view"]["slots"]}


def short(seed=0):
    return {**CFG, "game": {**CFG["game"], "seed": seed, "lives": 2, "life": 30, "gap": 100}}


class Stay:
    """哪儿也不去，挑第一个摊子。"""

    def __init__(self, world, visible):
        pass

    def go(self, day, here, want, stalls):
        return here

    def choose(self, day, want, stalls):
        return next(iter(stalls))

    def observe(self, day, p, seen):
        pass


class TestWorld(unittest.TestCase):
    def test_same_seed_same_world(self):
        def history(seed):
            w = World(seed, SLOTS, **CFG["world"])
            out = []
            for _ in range(200):
                w.step()
                out.append(tuple(w.value(p, s) for p in w.people for s in SLOTS))
            return out
        self.assertEqual(history(3), history(3))
        self.assertNotEqual(history(3), history(4))

    def test_macro_slow_micro_fast(self):
        w = World(0, SLOTS, **CFG["world"])
        for taus in w.tau.values():
            layer = [[t for n, t in enumerate(taus) if w.depth[n] == d] for d in range(3)]
            self.assertLess(max(layer[2]), min(layer[1]))      # 人比村快
            self.assertLess(max(layer[1]), min(layer[0]))      # 村比地区快

    def test_since_and_source(self):
        """since 和逐日盯着看的结果一致；source 往上第一个有自己值的节点。"""
        w = World(5, SLOTS, **CFG["world"])
        nodes = range(len(w.depth))
        last = {s: [w.value(n, s) for n in nodes] for s in SLOTS}
        changed = {s: [0] * len(w.depth) for s in SLOTS}
        for _ in range(600):
            w.step()
            for s in SLOTS:
                for n in nodes:
                    if w.value(n, s) != last[s][n]:
                        last[s][n], changed[s][n] = w.value(n, s), w.day
        self.assertEqual(w.since, changed)
        self.assertTrue(any(d > 0 for s in SLOTS for d in changed[s]))
        for s in SLOTS:
            for n in nodes:
                src = w.source(n, s)
                self.assertIsNotNone(w.own[s][src])
                self.assertTrue(all(w.own[s][m] is None for m in w.chain(n)[w.depth[src] + 1:]))

    def test_distance(self):
        w = World(0, SLOTS, **CFG["world"])
        a, b, c = w.villages[0], w.villages[1], w.villages[-1]
        self.assertEqual([w.distance(a, a), w.distance(a, b), w.distance(a, c)], [0, 0, 1])

    def test_play_every_day(self):
        lives = play(short(), Stay)
        self.assertEqual([len(log) for log in lives], [30, 30])

    def test_player_with_defaults(self):
        """一路回车：留在原地、找默认的那个人，能玩完一整局。"""
        cfg = short()
        with mock.patch("strata.__main__.load", return_value=cfg), mock.patch("sys.argv", ["strata"]), \
                mock.patch("builtins.input", return_value=""), mock.patch("builtins.print") as out:
            main()
        self.assertRegex(out.call_args.args[0], r"第 1 世 \d+/30，第 2 世 \d+/30")


if __name__ == "__main__":
    unittest.main()
