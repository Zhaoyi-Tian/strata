import unittest

from strata import Env, load, play
from strata.config import ROOT
from stratabench.agents import Anyone, Inference

CFG = load(ROOT / "config" / "more-memory.toml")


def short(seed=0):
    return {**CFG, "game": {**CFG["game"], "seed": seed, "lives": 2, "life": 20, "gap": 100}}


class TestMoreMemory(unittest.TestCase):
    def test_config(self):
        self.assertEqual(CFG["world"]["size"], [3, 3, 8])
        hidden = [s["name"] for s in CFG["view"]["slots"] if not s["visible"]]
        self.assertEqual(hidden, ["守不守信", "货真不真"])

    def test_text_game_reveals_both_hidden_traits(self):
        env = Env(short())
        env.reset()
        deals = []
        while not env.done:
            obs, _, info = env.step("继续" if env.life_ended else env.legal_actions()[0])
            self.assertTrue(info["parse_ok"])
            deals += [line for line in obs.splitlines() if "回去一验" in line]
        self.assertTrue(deals)
        for line in deals:
            self.assertRegex(line, r"(守信|短秤)，(真货|掺假)")

    def test_baselines_still_ordered(self):
        score = {make: sum(sum(log) for seed in range(3) for log in play(short(seed), make)) for make in (Anyone, Inference)}
        self.assertLess(score[Anyone], score[Inference])


if __name__ == "__main__":
    unittest.main()
