"""机制行为、组合、私有证据与公开文本的边界。测试固定世界仅用于建立可判定情景。"""

import io
import itertools
import json
import random
import subprocess
import sys
import unittest
import uuid
from copy import deepcopy
from pathlib import Path

from strata import DeliverMessage, Env, load
from strata.mechanisms.prospective import Prospective
from strata.mechanisms.reference_orders import ReferenceOrders
from strata.mechanisms.revisions import Revisions
from strata.mechanisms.rumor import Rumor
from stratabench.dsh_env import Episode

NAMES = ("rumor", "reference_orders", "revisions", "prospective", "distraction")


def config(enabled=(), life=8, lives=2, gap=5):
    cfg = load()
    cfg["game"].update(life=life, lives=lives, gap=gap)
    for name in NAMES:
        cfg["mechanisms"][name]["enabled"] = name in enabled
    return cfg


def stable(mechanisms, **kwargs):
    cfg = config(**kwargs)
    cfg["world"]["tau"] = 10**12
    env = Env(cfg, mechanisms=mechanisms)
    w = env.world
    for village in w.villages:
        for i, person in enumerate(w.residents[village]):
            w.own["卖什么"][person] = ("铁", "茶", "盐")[i % 3]
            w.own["守不守信"][person] = "守信"
    env.game.order_at = lambda day: {"卖什么": "铁", "守不守信": "守信"}
    return env


def skip_all(env):
    for _ in range(300):
        if env.done:
            return
        env.step("继续" if env.life_ended else "不做")
    raise AssertionError("game did not terminate")


def matching_person(env):
    return next(p for p, seen in env.ask.stalls.items() if all(seen[s] == env.ask.want[s] for s in env.game.visible))


class TestSwitches(unittest.TestCase):
    def test_each_mechanism_can_trigger_alone(self):
        for name in NAMES:
            cfg = config((name,))
            if "rate" in cfg["mechanisms"][name]:
                cfg["mechanisms"][name]["rate"] = 1
            env = stable([], life=8)
            # 用配置工厂生成单项，再放入固定场景；没有其他机制作前置。
            from strata.mechanisms import configured
            env.game.mechanisms = configured(cfg)
            env.reset()
            for _ in range(4):
                env.step(f"找 {env.name(matching_person(env))}")
            kind = {"rumor": "rumor", "reference_orders": "reference_order", "revisions": "revision",
                    "prospective": "task_issued", "distraction": "distraction"}[name]
            self.assertIn(kind, [event["kind"] for event in env.game.audit], name)

    def test_all_32_combinations_finish_and_keep_world_calendar(self):
        for bits in itertools.product((False, True), repeat=5):
            enabled = [name for name, bit in zip(NAMES, bits, strict=True) if bit]
            with self.subTest(enabled=enabled):
                env = Env(config(enabled, life=3))
                env.reset()
                skip_all(env)
                self.assertEqual(env.game.days_played, 6)
                self.assertEqual(env.world.day, 16)
                self.assertEqual({m.name for m in env.game.mechanisms}, set(enabled))
                forbidden = {"rumor": "rumor", "reference_orders": "reference_order", "revisions": "revision",
                             "prospective": "task_issued", "distraction": "distraction"}
                for name in set(NAMES) - set(enabled):
                    self.assertNotIn(forbidden[name], [event["kind"] for event in env.game.audit])

    def test_explicit_empty_overrides_config_and_reset_replays(self):
        cfg = config(NAMES)
        off = Env(cfg, mechanisms=[])
        plain = Env(config())
        self.assertEqual(off.reset(), plain.reset())
        self.assertEqual(off.instructions, plain.instructions)
        env = Env(cfg)
        self.assertEqual(env.truth()["mechanisms"]["states"], {})
        first = env.reset()
        skip_all(env)
        audit, scores, truth = deepcopy(env.game.audit), env.lives, env.truth()
        self.assertEqual(env.reset(), first)
        skip_all(env)
        self.assertEqual((env.game.audit, env.lives, env.truth()), (audit, scores, truth))

    def test_distraction_is_independent_and_does_not_move_other_random_streams(self):
        left, right = Env(config(("rumor", "prospective"))), Env(config(("rumor", "prospective", "distraction")))
        left.reset()
        right.reset()
        for _ in range(6):
            left.step("不做")
            right.step("不做")
        self.assertEqual(left.world.rng.getstate(), right.world.rng.getstate())
        self.assertEqual(left.truth()["nodes"], right.truth()["nodes"])
        self.assertEqual(left.game.audit, [e for e in right.game.audit if e["kind"] != "distraction"])
        standalone = Env(config(("distraction",)))
        self.assertIn("闲聊", standalone.reset())
        self.assertGreater(standalone.game.mechanism("distraction").count, 0)

    def test_validation(self):
        for key, value in (("rate", -0.1), ("rate", True), ("max_delay", -1), ("all_truthful", "yes")):
            cfg = config(("rumor",))
            cfg["mechanisms"]["rumor"][key] = value
            self.assertRaises(ValueError, Env, cfg)
        cfg = config(("prospective",))
        del cfg["view"]["lines"]["commission"]
        self.assertRaisesRegex(ValueError, "commission", Env, cfg)
        cfg = config()
        cfg["mechanisms"]["typo"] = {"enabled": True}
        self.assertRaises(ValueError, Env, cfg)


class TestRumor(unittest.TestCase):
    def test_old_truth_and_fabrication_are_distinct(self):
        for honest in (True, False):
            rumor = Rumor(rate=1, min_delay=2, max_delay=2, all_truthful=honest)
            env = stable([rumor])
            env.reset()
            self.assertIsNone(rumor.last)  # 世界还没有两天历史
            for person in env.world.people:
                env.world.own["守不守信"][person] = "短秤"
            env.step("不做")
            last = rumor.last
            self.assertEqual((last["statement_day"], last["heard_day"]), (0, 2))
            self.assertEqual(last["historical"]["value"], "守信")
            self.assertEqual(last["current_value"], "短秤")
            self.assertTrue(last["stale"])
            self.assertEqual(last["fabricated"], not honest)
            self.assertEqual(last["claimed_value"], "守信" if honest else "短秤")
            self.assertNotIn("fabricated", env.observation())

    def test_snapshots_include_travel_and_afterlife_without_changing_rng(self):
        rumor = Rumor(rate=1, max_delay=20, all_truthful=True)
        env = stable([rumor], life=3, gap=4)
        env.reset()
        distant = next(v for v in env.world.villages if env.world.distance(v, env.game.here))
        env.step(f"去 {env.name(distant)}")
        self.assertIn(2, [day for day, _ in rumor.history])
        env.step("不做")
        env.step("不做")
        self.assertTrue(env.life_ended)
        env.step("继续")
        self.assertEqual([day for day, _ in rumor.history], list(range(9)))
        before = env.world.rng.getstate()
        rumor.on(env.game, "news")
        self.assertEqual(env.world.rng.getstate(), before)


class TestReferences(unittest.TestCase):
    def test_no_history_falls_back_and_wrong_person_rejects_good_goods(self):
        reference = ReferenceOrders(rate=1)
        env = stable([reference])
        opening = env.reset()
        self.assertFalse(env.ask.reference)
        self.assertNotIn("那个人", opening)
        person = matching_person(env)
        env.step(f"找 {env.name(person)}")
        order = env.game.order
        self.assertEqual(order.target, person)
        self.assertEqual(order.hops, 1)
        self.assertEqual(env.ask.reference, {"kind": "transaction", "day": 1, "slot": "卖什么", "value": "铁"})
        self.assertNotIn("target", env.ask.reference)
        snapshot = env.ask
        snapshot.reference["day"] = 999
        self.assertEqual(env.ask.reference["day"], 1)
        wrong = next(p for p in env.ask.stalls if p != person and env.ask.stalls[p]["卖什么"] == "铁")
        feedback, _, info = env.step(f"找 {env.name(wrong)}")
        self.assertIn("不是口信里指定的人", feedback)
        self.assertIn("守不守信：守信", feedback)  # 不能把指称错误谎报为短秤
        self.assertEqual(env.game.log[:2], [True, False])
        self.assertIn("wrong_person", [e["kind"] for e in info["events"]])

    def test_two_hops_resolve_through_public_order_history(self):
        class Last:
            def random(self):
                return 0

            def choice(self, values):
                return values[-1]

        reference = ReferenceOrders(rate=1)
        reference.rng = lambda *args: Last()
        env = stable([reference])
        env.reset()
        person = matching_person(env)
        env.step(f"找 {env.name(person)}")
        env.step(f"找 {env.name(person)}")
        self.assertEqual(env.game.order.hops, 2)
        self.assertEqual(env.game.order.target, person)
        self.assertEqual(env.ask.reference, {"kind": "order", "day": 2})
        self.assertIn("世界第 2 天东家那张口信里指定的人", env.observation())
        self.assertEqual(reference.orders[-1]["antecedent_order"], "order:2")


class TestRevisions(unittest.TestCase):
    def test_shortcut_waits_for_each_revision_and_latest_order_is_scored(self):
        revision = Revisions(rate=1)
        env = stable([revision])
        env.reset()
        original = dict(env.ask.want)
        person = matching_person(env)
        feedback, _, _ = env.step(f"找 {env.name(person)}")
        self.assertIn("改主意", feedback)
        self.assertEqual((env.world.day, env.game.days_played, env.ask.kind), (1, 0, "choose"))
        self.assertNotEqual(env.ask.want, original)
        env.step(f"找 {env.name(matching_person(env))}")
        self.assertEqual(env.game.days_played, 0)
        self.assertEqual(env.game.order.version, 3)
        env.step(f"找 {env.name(matching_person(env))}")
        self.assertEqual(env.game.log, [True])
        revisions = [event for event in env.game.audit if event["kind"] == "revision"]
        self.assertEqual([event["version"] for event in revisions], [2, 3])

    def test_cross_region_keeps_order_identity_and_death_does_not_revise(self):
        env = stable([Revisions(rate=1)])
        env.reset()
        identity = env.game.order.id
        distant = next(v for v in env.world.villages if env.world.distance(v, env.game.here))
        feedback, _, _ = env.step(f"去 {env.name(distant)}")
        self.assertIn("改主意", feedback)
        self.assertEqual((env.world.day, env.game.days_played), (2, 1))
        self.assertEqual(env.game.order.id, identity)
        short = stable([Revisions(rate=1)], life=1)
        short.reset()
        distant = next(v for v in short.world.villages if short.world.distance(v, short.game.here))
        short.step(f"去 {short.name(distant)}")
        self.assertTrue(short.life_ended)
        self.assertFalse(any(e["kind"] == "revision" for e in short.game.audit))

    def test_revising_a_referenced_order_drops_the_reference(self):
        revision, reference = Revisions(rate=1), ReferenceOrders(rate=1)
        env = stable([reference, revision])
        env.reset()
        # 建立一次已向玩家反馈的真实交易，下一单就会点名找他。
        while env.game.days_played == 0:
            env.step(f"找 {env.name(matching_person(env))}")
        self.assertIsNotNone(env.game.order.target)
        old = env.game.want["卖什么"]
        feedback, _, _ = env.step("留下")
        self.assertIn("不必再找", feedback)
        self.assertNotEqual(env.game.want["卖什么"], old)
        self.assertIsNone(env.game.order.target)
        self.assertIsNone(env.ask.reference)
        self.assertEqual(env.ask.version, 2)
        self.assertEqual(env.game.order.hops, 0)
        self.assertTrue(reference.orders[-1]["revoked"])           # 以后的两跳指称不能再顺着它指过去


class TestProspective(unittest.TestCase):
    def setup_task(self, **kwargs):
        mechanism = Prospective(rate=0)
        env = stable([mechanism], **kwargs)
        env.reset()
        village = next(v for v in env.world.villages if v != env.game.here and env.world.distance(env.game.here, v) == 0)
        person = env.world.residents[village][0]
        task = mechanism.issue(env.game, next(iter(env.ask.stalls)), person, "北桥已经修好了")
        return env, mechanism, task

    def test_opportunity_is_not_a_reminder_and_delivery_costs_no_day(self):
        env, mechanism, task = self.setup_task()
        feedback, _, _ = env.step(f"去 {env.name(task['village'])}")
        self.assertEqual(task["status"], "open")
        self.assertNotIn("北桥", feedback + env.observation())
        self.assertNotIn("北桥", " ".join(env.legal_actions()))
        before = (env.world.day, env.game.days_played, dict(env.ask.want), env.ask.kind, env.world.rng.getstate())
        person = env.name(task["recipient"])
        wrong_person = env.name(next(p for p in env.ask.stalls if p != task["recipient"]))
        env.step(f"传话 {wrong_person} 北桥已经修好了")
        wrong = env.step(f"传话 {person} 北桥坏了")[0]
        correct = env.step(f"传话 {person} 北桥， 已经 修好了！")[0]
        self.assertEqual(wrong, correct)
        self.assertEqual(task["status"], "completed")
        env.step(f"传话 {person} 北桥已经修好了")
        self.assertEqual((env.world.day, env.game.days_played, env.ask.want, env.ask.kind, env.world.rng.getstate()), before)
        self.assertEqual(mechanism.metrics()["completed"], 1)
        self.assertEqual(mechanism.metrics()["incorrect"], 2)
        self.assertEqual(mechanism.metrics()["duplicates"], 1)
        env.step("不做")
        self.assertEqual(mechanism.metrics()["missed"], 0)

    def test_skipping_closes_window_and_out_of_village_actions_are_rejected(self):
        env, mechanism, task = self.setup_task()
        self.assertFalse(env.step(f"传话 {env.name(task['recipient'])} 北桥已经修好了")[2]["parse_ok"])
        env.step(f"去 {env.name(task['village'])}")
        env.step("不做")
        self.assertEqual(task["status"], "missed")
        env.step(f"传话 {env.name(task['recipient'])} 北桥已经修好了")
        self.assertEqual(mechanism.metrics()["completed"], 0)
        self.assertEqual(mechanism.metrics()["missed"], 1)

    def test_pending_tasks_survive_death_and_untriggered_are_not_failures(self):
        mechanism = Prospective(rate=0)
        env = stable([mechanism], life=1, gap=4)
        env.reset()
        rebirth = random.Random("0:spawn:2").choice(env.world.villages)
        village = next(v for v in env.world.villages if v not in (env.game.here, rebirth))
        task = mechanism.issue(env.game, next(iter(env.ask.stalls)), env.world.residents[village][0], "北桥已经修好了")
        env.step("不做")
        env.step("继续")
        self.assertEqual(task["status"], "pending")
        self.assertNotIn(task["message"], env.observation())
        env.step("不做")
        self.assertTrue(env.done)
        self.assertEqual(mechanism.metrics()["untriggered"], 1)
        self.assertEqual(mechanism.metrics()["opportunities"], 0)
        self.assertIsNone(mechanism.metrics()["completion_rate"])

    def test_disabled_action_and_invalid_core_messages(self):
        off = Env(config())
        off.reset()
        self.assertFalse(off.step("传话 铁匠 你好")[2]["parse_ok"])
        env, _, _ = self.setup_task()
        person = next(iter(env.ask.stalls))
        for message in (None, "", "。", "  "):
            self.assertRaises(ValueError, env.game.step, DeliverMessage(person, message))


class TestDshMechanisms(unittest.TestCase):
    def test_real_utf8_jsonl_subprocess(self):
        workspace = Path(__file__).resolve().parents[1]
        cache = (workspace / "results" / "tests").resolve()
        if not cache.is_relative_to(workspace):
            raise RuntimeError("test artifacts must stay in the workspace")
        cache.mkdir(parents=True, exist_ok=True)
        # Windows 沙箱中 tempfile 的 0700 目录可能无法被子进程访问；使用现有缓存目录内的唯一文件。
        identity = uuid.uuid4().hex
        cfg, log = cache / f"game {identity}.toml", cache / f"env {identity}.jsonl"
        try:
            cfg.write_text('[game]\nlives=1\nlife=1\ngap=0\n'
                           '[mechanisms.prospective]\nenabled=true\nrate=1\n', encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-m", "stratabench.dsh_env", "--config", str(cfg), "--seed", "0", "--log", str(log)],
                input=json.dumps({"action": "不做"}, ensure_ascii=False) + "\n",
                encoding="utf-8", capture_output=True, timeout=20, check=True,
            )
            initial, final = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertIn("东家", initial["feedback"])
            self.assertTrue(final["done"])
            self.assertEqual(final["mechanism_scores"]["prospective"]["untriggered"], 1)
            self.assertNotIn("truth", final)
            self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 2)
        finally:
            cfg.unlink(missing_ok=True)
            log.unlink(missing_ok=True)

    def test_delivery_through_episode_uses_same_text_and_no_day(self):
        cfg = config(("prospective",), life=4)
        cfg["world"]["size"] = [1, 3, 4]
        cfg["mechanisms"]["prospective"]["rate"] = 1
        episode = Episode(cfg, 0, io.StringIO())
        task = episode.env.game.mechanism("prospective").tasks[0]
        packet = episode.step(f"去 {episode.env.name(task['village'])}")
        before = packet["day"], packet["days_played"]
        packet = episode.step(f"传话 {episode.env.name(task['recipient'])} {task['message']}")
        self.assertEqual((packet["day"], packet["days_played"]), before)
        self.assertEqual(task["status"], "completed")
        self.assertNotIn("mechanism_scores", packet)
        self.assertNotIn("task_ids", packet)

    def test_same_text_interface_private_audit_and_final_separate_scores(self):
        cfg, stream = config(NAMES, life=3), io.StringIO()
        episode = Episode(cfg, 2, stream)
        env = Env(cfg, seed=2)
        self.assertEqual(env.reset(), episode.initial["feedback"])
        self.assertEqual(episode.initial["protocol"], "part-a-v2")
        while not env.done:
            feedback, _, _ = env.step("不做")
            if env.life_ended:
                feedback += "\n" + env.step("继续")[0]
            packet = episode.step("不做")
            self.assertEqual(packet["feedback"], feedback)
            self.assertEqual(packet["observation"], env.observation())
            for private in ("truth", "mechanism_events", "target", "fabricated", "task_ids"):
                self.assertNotIn(private, packet)
            if not packet["done"]:
                self.assertNotIn("mechanism_scores", packet)
        self.assertEqual(packet["mechanism_scores"], env.game.mechanism_scores())
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertTrue(all("truth" in record for record in records))
        self.assertIn("config", records[0])
        self.assertTrue(any(record.get("info", {}).get("mechanism_events") for record in records))


if __name__ == "__main__":
    unittest.main()
