"""随机配置 × 随机动作（含乱写的动作），检查任何走法下都该成立的事。"""

import json
import random
import unittest
from copy import deepcopy

from strata import Env, load, play
from strata.config import ROOT
from stratabench.agents import AGENTS, Oracle

NAMES = ("rumor", "reference_orders", "revisions", "prospective", "distraction")
JUNK = ["", "找", "去", "找 不存在的人", "去 火星", "留下 留下", "不做吧", "传话", "传话 某人 你好", "「不做。」", 123]


def random_cfg(rng):
    cfg = load(ROOT / "config" / "more-memory.toml") if rng.random() < 0.2 else load()
    cfg["world"].update(size=[rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 6)], tau=rng.choice([1, 10, 50]),
                        ratio=rng.choice([1, 5, 10]), mu=rng.choice([0, 0.3, 1]))
    cfg["game"].update(lives=rng.randint(1, 3), life=rng.randint(1, 6), gap=rng.randint(0, 5), seed=rng.randint(0, 999))
    if len([s for s in cfg["view"]["slots"] if not s["visible"]]) == 1:       # 机制的台词只写在默认世界观里
        for name in NAMES:
            m = cfg["mechanisms"][name]
            m["enabled"] = rng.random() < 0.5
            if "rate" in m:
                m["rate"] = rng.choice([0, 0.3, 1])
        cfg["mechanisms"]["rumor"].update(min_delay=rng.randint(0, 2), max_delay=rng.randint(2, 6),
                                          all_truthful=rng.random() < 0.5)
    return cfg


def random_game(cfg, rng):
    """随机玩一局，边玩边检查；返回全部文字和动作，用来比重放。"""
    env, case = Env(deepcopy(cfg)), unittest.TestCase()
    texts, actions = [env.instructions, env.reset()], []
    while not env.done:
        legal, before = env.legal_actions(), (env.game.days_played, env.world.day)
        if rng.random() < 0.15:
            action = rng.choice(JUNK)
        elif rng.random() < 0.1 and env.game.mechanism("prospective") and env.ask.kind != "death":
            action = f"传话 {env.name(rng.choice(list(env.ask.stalls)))} {rng.choice(cfg['view']['mechanism_text']['messages'])}"
        else:
            action = rng.choice(legal)
        obs, _, info = env.step(action)
        actions.append(action)
        texts.append(obs)
        json.dumps(info, ensure_ascii=False)
        case.assertEqual(info["life_ended"], env.life_ended)
        if action in legal:
            case.assertTrue(info["parse_ok"], action)
        if not info["parse_ok"]:
            case.assertEqual((env.game.days_played, env.world.day), before, "看不懂的动作不该耗时间")
        case.assertNotIn("{", obs)
        case.assertLess(len(actions), 2000)
    g = cfg["game"]
    case.assertEqual([len(log) for log in env.lives], [g["life"]] * g["lives"])
    case.assertEqual(env.world.day, g["lives"] * (g["life"] + g["gap"]))
    for e in env.game.audit:
        if e["kind"] == "rumor":
            case.assertEqual(e["fabricated"], e["claimed_value"] != e["historical"]["value"])
            case.assertEqual(e["stale"], e["historical"]["value"] != e["current_value"])
        if e["kind"] == "reference_order" and e["public"]["kind"] == "transaction":
            pub = e["public"]
            case.assertTrue(any(t["day"] == pub["day"] and t["person"] == e["target"] for t in env.game.trades))
    return texts, actions


class Replay:
    def __init__(self, actions):
        self.actions = iter(actions)

    def random(self):
        return 1.0                                              # 永远不走乱写和传话的分支

    def choice(self, legal):
        return next(self.actions)


class TestFuzz(unittest.TestCase):
    def test_random_games_keep_invariants_and_replay(self):
        rng = random.Random(0)
        for k in range(300):
            cfg = random_cfg(rng)
            with self.subTest(k=k, game=cfg["game"], world=cfg["world"]):
                texts, actions = random_game(cfg, random.Random(k))
                self.assertEqual(random_game(cfg, Replay(actions))[0], texts)

    def test_baselines_in_random_worlds(self):
        rng = random.Random(1)
        for k in range(60):
            cfg = load()
            cfg["world"].update(size=[rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 6)], mu=rng.choice([0, 0.3, 1]))
            cfg["game"].update(lives=rng.randint(1, 3), life=rng.randint(1, 15), gap=rng.randint(0, 50), seed=k)
            for make in AGENTS:
                with self.subTest(k=k, agent=make.name):
                    events = []
                    lives = play(cfg, make, say=lambda kind, events=events, **kw: events.append(kind))
                    self.assertEqual([len(log) for log in lives], [cfg["game"]["life"]] * cfg["game"]["lives"])
                    self.assertEqual(sum(map(sum, lives)), events.count("done"))
                    if make is Oracle:
                        self.assertNotIn("fail", events, "全知只做一定成的单")


if __name__ == "__main__":
    unittest.main()
