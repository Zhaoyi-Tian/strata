"""Recompute the published Part A results from recorded actions, without model calls.

Run on the code that produced it (tag part-a-v1); later versions changed Part A and the private state:
    git worktree add ../strata-v1 part-a-v1 && cd ../strata-v1
    uv run python experiments/part-a-2026-11-26/verify.py
The trajectory contains public feedback and hashes of the original private state;
the current Game/Env reconstructs that state during replay.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from strata import Env, load


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value):
    # Normalize integer node keys exactly as JSONL serialization does.
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def equal(actual, expected, label):
    if actual != expected:
        raise ValueError(f"{label} does not match the published record")


def outcomes(events):
    counts = Counter(event["outcome"] for event in events if event["outcome"] != "road")
    return {"successes": counts["done"], "failures": counts["fail"], "skips": counts["skip"]}


def calculate(directory):
    records = [json.loads(line) for line in (directory / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()]
    initial = records[0]
    equal(initial["kind"], "start", "initial record")
    cfg = initial["config"]
    configured = load(directory / "game.toml")
    for section in ("world", "game", "mechanisms"):
        equal(configured[section], cfg[section], f"game configuration {section}")
    env = Env(cfg)
    equal(env.reset(), initial["feedback"], "opening feedback")
    equal(digest(env.truth()), initial["truth_sha256"], "opening truth")
    events = list(env.game.audit)
    per_life = [Counter() for _ in range(cfg["game"]["lives"])]
    actions = invalid = continues = 0

    for index, row in enumerate(records[1:], 1):
        before_phase, life, here = env.game.phase, env.game.life, env.game.here
        facts = {person: {slot: env.world.value(person, slot) for slot in env.world.slots}
                 for person in env.world.people}
        equal(row["kind"], "continue" if before_phase == "death" else "step", f"transition {index} kind")
        feedback, _, info = env.step(row["action"])
        equal(feedback, row["feedback"], f"transition {index} feedback")
        equal(digest(info), row["info_sha256"], f"transition {index} info")
        equal(digest(env.truth()), row["truth_sha256"], f"transition {index} truth")
        if row["kind"] == "step":
            actions += 1
            invalid += not info["parse_ok"]
        else:
            continues += 1
        added = info.get("mechanism_events", [])
        events.extend(added)
        choices = {event["order_id"]: event for event in added if event["kind"] == "choice"}
        for settlement in (event for event in added if event["kind"] == "settlement"):
            equal(settlement["life"], life, f"transition {index} settlement life")
            stat, outcome = per_life[life - 1], settlement["outcome"]
            stat["days"] += 1
            stat[outcome] += 1
            if outcome == "road":
                continue
            choice = choices[settlement["order_id"]]
            candidates = [person for person in env.world.people
                          if (choice["target"] is None or person == choice["target"])
                          and all(facts[person][slot] == value for slot, value in choice["want"].items())]
            local = [person for person in candidates if env.world.parent[person] == here]
            stat["global_no_qualified_person"] += not candidates
            stat["selected_village_no_qualified_person"] += bool(candidates) and not local
            stat["local_qualified_but_unsuccessful"] += bool(local) and outcome != "done"

    equal(env.done, True, "episode completion")
    lives = []
    for index, stat in enumerate(per_life):
        equal(stat["days"], cfg["game"]["life"], f"life {index + 1} days")
        equal(stat["done"], sum(env.lives[index]), f"life {index + 1} score")
        equal(sum(stat[key] for key in ("done", "fail", "skip", "road")), stat["days"], "day decomposition")
        equal(stat["done"] + stat["road"] + sum(stat[key] for key in (
            "global_no_qualified_person", "selected_village_no_qualified_person", "local_qualified_but_unsuccessful"
        )), stat["days"], "feasibility decomposition")
        lives.append({"life": index + 1, "days": stat["days"], **outcomes_from_stat(stat),
                      "road_days": stat["road"], "success_rate": stat["done"] / stat["days"],
                      **{key: stat[key] for key in ("global_no_qualified_person", "selected_village_no_qualified_person",
                                                  "local_qualified_but_unsuccessful")}})

    settlements = [event for event in events if event["kind"] == "settlement"]
    rumors = [event for event in events if event["kind"] == "rumor"]
    references = [event for event in events if event["kind"] == "reference_order"]
    reference_ids = {event["id"] for event in references}
    revisions = [event for event in events if event["kind"] == "revision"]
    revised_ids = {event["order_id"] for event in revisions}
    reference_settlements = [event for event in settlements if event["order_id"] in reference_ids]
    tasks = {event["id"]: event for event in events if event["kind"] == "task_issued"}
    completions = [{"task_id": task_id, "issued_life": tasks[task_id]["life"], "completed_life": event["life"],
                    "issued_day": tasks[task_id]["day"], "completed_day": event["day"]}
                   for event in events if event["kind"] == "message_delivered" and event["result"] == "completed"
                   for task_id in event["task_ids"]]

    calls = read(directory / "calls.json")
    equal([call["id"] for call in calls], list(range(1, len(calls) + 1)), "request sequence")
    equal(sum(call["purpose"] == "task" for call in calls), actions, "task requests and model actions")
    usage = Counter()
    for call in calls:
        usage.update(call["usage"])
    totals = {key: sum(life[key] for life in lives) for key in lives[0] if key not in ("life", "success_rate")}
    return {
        "protocol": initial["protocol"], "completed": env.done, "final_world_day": env.world.day,
        "purchase": {**totals, "success_rate": totals["successes"] / totals["days"], "per_life": lives},
        "mechanisms": {
            "rumor": {"messages": len(rumors), "fabricated": sum(event["fabricated"] for event in rumors),
                      "historical_fact_differs_from_current": sum(event["stale"] for event in rumors)},
            "reference_orders": {"orders": len(references), "one_hop": sum(event["hops"] == 1 for event in references),
                                 "two_hop": sum(event["hops"] == 2 for event in references),
                                 **outcomes(reference_settlements),
                                 "wrong_person": sum(event["wrong_person"] for event in reference_settlements)},
            "revisions": {"events": len(revisions), "orders": len(revised_ids),
                          **outcomes([event for event in settlements if event["order_id"] in revised_ids])},
            "prospective": {**env.game.mechanism_scores()["prospective"],
                            "cross_life_completed": sum(item["completed_life"] > item["issued_life"] for item in completions),
                            "completions": completions},
            "distraction": {"messages": sum(event["kind"] == "distraction" for event in events)},
        },
        "interaction": {"model_requests": len(calls), "model_actions": actions, "invalid_actions": invalid,
                        "automatic_continues": continues,
                        "summary_calls": sum(call["purpose"] == "compaction" for call in calls), "usage": dict(usage)},
    }


def outcomes_from_stat(stat):
    return {"successes": stat["done"], "failures": stat["fail"], "skips": stat["skip"]}


def verify(directory):
    manifest = read(directory / "manifest.json")
    for name, expected in manifest["published_files_sha256"].items():
        content = (directory / name).read_text(encoding="utf-8").encode("utf-8")
        equal(hashlib.sha256(content).hexdigest(), expected, f"file {name}")
    result = calculate(directory)
    equal(result, read(directory / "results.json"), "recomputed results")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = verify(args.directory.resolve())
    print(json.dumps({"verified": True, "days": result["purchase"]["days"],
                      "purchase_successes": result["purchase"]["successes"],
                      "message_completions": result["mechanisms"]["prospective"]["completed"],
                      "model_actions": result["interaction"]["model_actions"]}))


if __name__ == "__main__":
    main()
