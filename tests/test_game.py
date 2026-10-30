import random
import unittest

from strata import Game, View, load
from strata.mechanisms import Mechanism

CFG = load()


def config(seed=0, life=3, gap=2, lives=3):
    return {**CFG, "game": {"seed": seed, "life": life, "gap": gap, "lives": lives}}


class TestGame(unittest.TestCase):
    def test_calendar_and_scores_at_every_decision_boundary(self):
        """独立记账：移动只扣路程，找人扣一天；死亡和结束处也检查日期。"""
        for seed in range(4):
            for life in (1, 2, 3, 7):
                for gap in (0, 2):
                    for route in ("stay", "far", "random"):
                        with self.subTest(seed=seed, life=life, gap=gap, route=route):
                            game = Game(config(seed, life, gap))
                            rng = random.Random(seed)
                            ask, paid = game.start(), 0
                            while ask is not None:
                                self.assertEqual(game.days_played, paid)
                                self.assertTrue(all(len(log) == life for log in game.lives))
                                completed = (game.life - 1) * (life + gap)
                                if ask.kind == "death":
                                    self.assertEqual(ask.day, completed + life)
                                    answer = None
                                else:
                                    self.assertEqual(ask.day, completed + len(game.log) + 1)
                                    self.assertLess(len(game.log), life)
                                    if ask.kind == "go":
                                        if route == "stay":
                                            answer = ask.here
                                        elif route == "random":
                                            answer = rng.choice(game.world.villages)
                                        else:
                                            answer = next(v for v in game.world.villages if game.world.distance(ask.here, v))
                                        paid += min(game.world.distance(ask.here, answer), life - len(game.log))
                                    else:
                                        answer = rng.choice([None, *ask.stalls])
                                        paid += 1
                                ask = game.step(answer)
                            self.assertTrue(game.done)
                            self.assertEqual(paid, 3 * life)
                            self.assertEqual(game.days_played, paid)
                            self.assertEqual([len(log) for log in game.lives], [life] * 3)
                            self.assertEqual(game.world.day, 3 * (life + gap))

    def test_travel_arrives_next_day_with_the_departure_order(self):
        events = []
        game = Game(config(), say=lambda kind, **kw: events.append((kind, kw)))
        start = game.start()
        dest = next(v for v in game.world.villages if game.world.distance(start.here, v))
        events.clear()
        arrival = game.step(dest)
        self.assertEqual((arrival.kind, arrival.day, arrival.here), ("choose", 2, dest))
        self.assertEqual(arrival.want, start.want)
        self.assertEqual(set(arrival.stalls), set(game.world.residents[dest]))
        self.assertEqual(game.log, [False])
        self.assertEqual([kind for kind, _ in events], ["travel", "stalls"])
        self.assertEqual(events[0][1]["village"], dest)

    def test_local_walk_and_stay_cost_no_day(self):
        for walk in (False, True):
            game = Game(config())
            start = game.start()
            dest = next(v for v in game.world.villages if v != start.here
                        and game.world.distance(start.here, v) == 0) if walk else start.here
            ask = game.step(dest)
            self.assertEqual((ask.day, ask.here, ask.kind), (1, dest, "choose"))
            self.assertEqual(game.days_played, 0)

    def test_last_day_trip_dies_before_arrival(self):
        events = []
        game = Game(config(life=1, gap=0, lives=1), say=lambda kind, **kw: events.append(kind))
        start = game.start()
        dest = next(v for v in game.world.villages if game.world.distance(start.here, v))
        events.clear()
        self.assertIsNone(game.step(dest))
        self.assertEqual((game.here, game.world.day, game.days_played), (start.here, 1, 1))
        self.assertEqual(game.lives, [[False]])
        self.assertEqual(events, ["travel", "death"])

    def test_trade_success_failure_and_wrong_goods(self):
        class Order(Mechanism):
            def order(self, game, want):
                person = game.world.residents[game.here][0]
                want = {s: game.world.value(person, s) for s in game.world.slots}
                if outcome != "done":
                    slot = game.visible[0] if outcome == "skip" else game.hidden[0]
                    want[slot] = next(v for v in game.world.slots[slot] if v != want[slot])
                return want

        for outcome in ("done", "fail", "skip"):
            with self.subTest(outcome=outcome):
                seen, events = [], []
                game = Game(config(life=1, gap=0, lives=1), mechanisms=[Order()],
                            observe=lambda day, p, values, seen=seen: seen.append(values),
                            say=lambda kind, events=events, **kw: events.append(kind))
                ask = game.start()
                person = next(iter(ask.stalls))
                game.step(ask.here)
                seen.clear()
                events.clear()
                game.step(person)
                self.assertEqual(game.lives, [[outcome == "done"]])
                self.assertEqual(events, [outcome, "death"])
                self.assertEqual(seen, [] if outcome == "skip" else [
                    {s: game.world.value(person, s) for s in game.hidden}])

    def test_lifecycle_and_invalid_nodes_do_not_advance(self):
        game = Game(config(life=1, gap=0, lives=1))
        self.assertIsNone(game.ask)
        self.assertFalse(game.done)
        self.assertRaises(RuntimeError, game.step, None)
        game.start()
        self.assertRaises(RuntimeError, game.start)
        for invalid in (None, -1, game.world.people[0], True, float(game.here)):
            before = game.ask
            self.assertRaises(ValueError, game.step, invalid)
            self.assertEqual((game.ask, game.days_played), (before, 0))
        game.step(game.here)
        for invalid in (-1, game.here, True, float(next(iter(game.stalls)))):
            before = game.ask
            self.assertRaises(ValueError, game.step, invalid)
            self.assertEqual((game.ask, game.days_played), (before, 0))
        game.step(None)
        self.assertRaises(RuntimeError, game.step, None)
        self.assertRaises(RuntimeError, game.start)

    def test_ask_is_a_snapshot(self):
        game = Game(config())
        ask = game.start()
        person = next(iter(ask.stalls))
        ask.want.clear()
        ask.stalls[person].clear()
        self.assertTrue(game.ask.want)
        self.assertTrue(game.ask.stalls[person])
        game.step(game.here)
        game.step(None)
        self.assertEqual(ask.day, 1)
        self.assertEqual(game.ask.day, 2)

    def test_core_rejects_invalid_durations(self):
        for key, values in {"lives": (0, -1, True, 1.5), "life": (0, -1, True, 1.5),
                            "gap": (-1, True, 1.5)}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    cfg = config()
                    cfg["game"][key] = value
                    self.assertRaises(ValueError, Game, cfg)

    def test_all_event_nodes_have_the_same_names_as_the_map(self):
        events = []
        game = Game(config(), say=lambda kind, **kw: events.append((kind, kw)))
        view = View(CFG["view"], game.world)
        names = [view.name(n) for n in game.world.villages]
        self.assertEqual(names, CFG["view"]["villages"][:len(names)])
        self.assertTrue(all(name in view.map() for name in names))
        ask = game.start()
        dest = next(v for v in game.world.villages if v != ask.here)
        game.step(dest)
        for kind, fields in events:
            text = view.say(kind, **fields)
            if "village" in fields:
                self.assertIn(fields["village"], game.world.villages)
                self.assertIn(view.name(fields["village"]), text)


if __name__ == "__main__":
    unittest.main()
