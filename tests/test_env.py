import hashlib
import unittest

from strata import Env, load, play
from strata.env import LAYERS
from strata.mechanisms import Mechanism
from stratabench import AGENTS

CFG = load()

# 加文本接口之前（c5eaed5），用原版 play() 跑出来的：每个采办在 seed 0、1、2 上每一世做成几单，以及逐日记录的指纹。
# 只改接口时这些必须不变。改了世界或玩法的规则，这里会变，那是对的：重新跑一遍，并同步 README 里的表。
BEFORE = {
    "随便找": ([[22, 45, 14, 42], [43, 7, 36, 15], [56, 43, 45, 79]], "90e586686d69872c"),
    "只信最新": ([[36, 41, 0, 0], [67, 11, 0, 0], [79, 90, 46, 79]], "be0900c2a6fcbca6"),
    "只信多数": ([[31, 52, 42, 22], [53, 2, 33, 44], [59, 48, 77, 65]], "1710e163be44a2fa"),
    "分层推断": ([[41, 81, 73, 47], [69, 32, 68, 51], [69, 85, 87, 89]], "2e8086f1b9efdfe8"),
    "全知": ([[78, 79, 81, 70], [88, 60, 86, 79], [96, 95, 95, 96]], "c505580aa40db5f2"),
}


def full(seed):
    return {**CFG, "game": {**CFG["game"], "seed": seed}}


def short(seed=0):
    return {**CFG, "game": {**CFG["game"], "seed": seed, "lives": 2, "life": 30, "gap": 100}}


def fingerprint(runs) -> str:
    flat = "".join("1" if x else "0" for lives in runs for log in lives for x in log)
    return hashlib.sha256(flat.encode()).hexdigest()[:16]


def drive(env, make, shortcut):
    """让规则采办打字玩文本版。shortcut：留在本村时直接回「找 X」，否则先回「留下」再回「找 X」。"""
    agent = make(env.world, env.game.visible)
    env.game.observe = agent.observe
    env.reset()
    while not env.done:
        ask = env.ask
        if ask.kind == "death":
            action = "继续"
        elif ask.kind == "go":
            dest = agent.go(ask.day, ask.here, ask.want, ask.stalls)
            if dest != ask.here:
                action = f"去 {env.name(dest)}"
            elif shortcut:
                p = agent.choose(ask.day, ask.want, ask.stalls)
                action = "不做" if p is None else f"找 {env.name(p)}"
            else:
                action = "留下"
        else:
            p = agent.choose(ask.day, ask.want, ask.stalls)
            action = "不做" if p is None else f"找 {env.name(p)}"
        _, _, info = env.step(action)
        assert info["parse_ok"], info["error"]
    return env.lives


class TestEnv(unittest.TestCase):
    def test_baselines_unchanged(self):
        for make in AGENTS:
            runs = [play(full(seed), make) for seed in range(3)]
            counts, sha = BEFORE[make.name]
            self.assertEqual([[sum(log) for log in lives] for lives in runs], counts, make.name)
            self.assertEqual(fingerprint(runs), sha, make.name)

    def test_text_same_as_play(self):
        """同一个采办，打字玩和回调玩，每一天都一样。"""
        for make in AGENTS:
            for shortcut in (True, False):
                self.assertEqual(drive(Env(short(1)), make, shortcut), play(short(1), make), make.name)

    def test_bad_action_costs_nothing(self):
        env = Env(short())
        first = env.reset()
        here = env.name(env.ask.here)
        for bad in ["随便说点什么", "找 不存在的人", "去 火星", ""]:
            obs, done, info = env.step(bad)
            self.assertFalse(info["parse_ok"])
            self.assertEqual((info["day"], info["phase"], done), (1, "go", False))
            self.assertTrue(obs.endswith(first.splitlines()[-1]))   # 原样再问一次
        env.step("留下")
        _, _, info = env.step(f"去 {here}")                         # 已经定在这儿了，不能再走
        self.assertFalse(info["parse_ok"])
        self.assertEqual(info["phase"], "choose")

    def test_lenient_format(self):
        env = Env(short())
        env.reset()
        p = env.name(next(iter(env.ask.stalls)))
        for ok in [f"找{p}。", f"「找 {p}」", f"  找 {p}  "]:
            self.assertEqual(env._parse(ok)[1], None, ok)
        v = env.name(env.world.villages[-1])
        self.assertEqual(env._parse(f"去{v}")[1], None)

    def test_lives_and_death(self):
        env = Env(short())
        obs = env.reset()
        deaths = 0
        while not env.done:
            obs, done, info = env.step("继续" if env.life_ended else "不做")
            if env.life_ended:
                deaths += 1
                self.assertTrue(info["life_ended"])
                self.assertEqual(env.legal_actions(), ["继续"])
                obs, _, _ = env.step("我把要记的写在这里")                # 这一问回什么都行
                self.assertIn("第 2 世", obs)
        self.assertEqual(deaths, 1)                                   # 两世之间一次；最后一世到头直接 done
        self.assertEqual([len(log) for log in env.lives], [30, 30])
        self.assertRaises(RuntimeError, env.step, "不做")

    def test_truth(self):
        env = Env(short(2))
        env.reset()
        for _ in range(20):
            env.step(env.legal_actions()[0])
        t, w = env.truth(), env.world
        seen = set(env.view.names["person"])
        self.assertTrue(seen)
        for n, node in t["nodes"].items():
            self.assertEqual(node["layer"], LAYERS[w.depth[n]])
            if w.depth[n] == 2:
                self.assertEqual(node["name"] is not None, n in seen)  # 没见过的人没有名字
            for s in w.slots:
                x = node[s]
                self.assertEqual(x["value"], w.value(n, s))
                self.assertIn(x["source"], w.chain(n))                 # 由自己或上面某一层决定
                self.assertEqual(x["own"], x["source"] == n)
                self.assertLessEqual(x["since"], t["day"])

    def test_reset_replays_same_world(self):
        env = Env(short(3))
        a = env.reset()
        env.step("不做")
        self.assertEqual(env.reset(), a)

    def test_mechanism_hooks(self):
        class Count(Mechanism):
            def __init__(self):
                self.orders = self.news_ = 0

            def order(self, game, want):
                self.orders += 1
                return want

            def news(self, game):
                self.news_ += 1

        m = Count()
        self.assertEqual(play(short(), AGENTS[0], mechanisms=[m]), play(short(), AGENTS[0]))  # 什么都不做的机制不改结果
        self.assertEqual(m.orders, m.news_)
        self.assertGreater(m.orders, 0)


if __name__ == "__main__":
    unittest.main()
