import io
import json
import unittest

from strata import Env, load
from strata.view import View
from stratabench.dsh_env import Episode

CFG = load()


class TestControl(unittest.TestCase):
    def test_routes_do_not_change_daily_orders_births_or_life_dates(self):
        def run(travel):
            env = Env({**CFG, "game": {**CFG["game"], "lives": 3, "life": 3, "gap": 5}}, seed=0)
            env.reset()
            days, births, orders = [], [], {}
            while not env.done:
                ask = env.ask
                if ask.kind == "death":
                    env.step("继续")
                    continue
                if ask.kind == "go":
                    orders[ask.day] = dict(ask.want)
                    if not env.game.log:
                        births.append(ask.here)
                        days.append(ask.day)
                    target = next(v for v in env.world.villages if env.world.distance(ask.here, v))
                    action = f"去 {env.name(target)}" if travel else "不做"
                else:
                    action = "不做"
                env.step(action)
            return days, births, orders, env.world.day

        stay, travel = run(False), run(True)
        self.assertEqual(stay[:2], travel[:2])
        self.assertEqual(stay[0], [1, 9, 17])
        self.assertEqual(stay[3], travel[3])
        for day in stay[2].keys() & travel[2].keys():
            self.assertEqual(stay[2][day], travel[2][day])

    def test_names_are_independent_of_visit_order_without_naming_unseen_people(self):
        a, b = View(CFG["view"]), View(CFG["view"])
        forward = {n: a.name("person", n) for n in [2, 9, 4]}
        reverse = {n: b.name("person", n) for n in [4, 9, 2]}
        self.assertEqual(forward, reverse)
        self.assertNotIn(15, a.names["person"])

    def test_current_screen_is_public_and_does_not_advance_or_repeat_feedback(self):
        env = Env(CFG, seed=0)
        env.reset()
        env.step(env.legal_actions()[0])
        before = env.truth()
        screen = env.observation()
        self.assertEqual(env.truth(), before)
        self.assertIn("当前订单", screen)
        self.assertIn("摊上", screen)
        self.assertNotIn("过秤", screen)
        self.assertNotIn("source_layer", screen)


class TestDshEpisode(unittest.TestCase):
    def test_public_packets_and_private_evaluation_log(self):
        log = io.StringIO()
        cfg = {**CFG, "game": {**CFG["game"], "lives": 2, "life": 2, "gap": 5}}
        episode = Episode(cfg, 0, log)
        packet = episode.initial
        self.assertNotIn("truth", packet)
        first_day = packet["day"]
        bad = episode.step("随便")
        self.assertFalse(bad["parse_ok"])
        self.assertEqual(bad["day"], first_day)
        self.assertEqual(bad["observation"], packet["observation"])
        transitions = []
        while not packet["done"]:
            packet = episode.step("不做")
            transitions.append(packet["feedback"])
            self.assertNotIn("truth", packet)
        self.assertEqual([len(life) for life in packet["lives"]], [2, 2])
        self.assertEqual(packet["days_played"], 4)
        self.assertTrue(any("第 2 世" in text for text in transitions))
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(sum(e["kind"] == "continue" for e in events), 1)
        self.assertTrue(all("truth" in event for event in events))


if __name__ == "__main__":
    unittest.main()
