"""python -m strata.demo：Part A 受控故事演示，不作为 benchmark 成绩。

固定初始陈列和人物守信值，提高触发率；所有动作、消息、日期和结算仍经过 Env/Game。
演示控制器可读真值以安排路线，不能拿它与被测 agent 比较。
"""

import json

from .config import load
from .env import Env


def build_demo():
    cfg = load()
    cfg["game"].update(seed=0, lives=1, life=6, gap=0)
    cfg["world"].update(size=[1, 3, 4], tau=10**12)
    for settings in cfg["mechanisms"].values():
        settings["enabled"] = True
        if "rate" in settings:
            settings["rate"] = 1
    cfg["mechanisms"]["rumor"].update(min_delay=1, max_delay=2, all_truthful=True)
    cfg["mechanisms"]["revisions"]["max_revisions"] = 1
    cfg["mechanisms"]["prospective"]["max_pending"] = 1
    env = Env(cfg)
    for village in env.world.villages:
        for index, person in enumerate(env.world.residents[village]):
            env.world.own["卖什么"][person] = ("铁", "茶", "盐")[index % 3]
            env.world.own["守不守信"][person] = "守信"
    return env


def demonstration():
    """返回实际运行的文字和私有审计；不把诊断答案插回玩家画面。"""
    env = build_demo()
    transcript = ["【受控演示：固定初始场景、提高触发率；以下动作由演示控制器安排，不是模型评测。】",
                  env.instructions, env.reset()]
    for _ in range(100):
        if env.done:
            break
        game, ask = env.game, env.ask
        prospective = game.mechanism("prospective")
        opened = next((task for task in prospective.tasks if task["status"] == "open"), None)
        if opened:
            action = f"传话 {env.name(opened['recipient'])} {opened['message']}"
        elif ask.kind == "go":
            target = game.order_state["target"]
            pending = next((task for task in prospective.tasks if task["status"] == "pending"), None)
            if target is not None:
                village = env.world.parent[target]
            elif pending is not None and game.days_played > 0:
                village = pending["village"]
            else:
                village = ask.here
            action = "留下" if village == ask.here else f"去 {env.name(village)}"
        else:
            target = game.order_state["target"]
            candidates = [p for p, seen in ask.stalls.items()
                          if (target is None or target == p) and all(seen[s] == ask.want[s] for s in game.visible)]
            action = f"找 {env.name(candidates[0])}" if candidates else "不做"
        feedback, _, _ = env.step(action)
        transcript.extend([f"> {action}", feedback])
    else:
        raise RuntimeError("demonstration did not finish")
    required = {"rumor", "reference_order", "revision", "task_issued", "message_delivered", "distraction"}
    if not required <= {event["kind"] for event in env.game.audit}:
        raise RuntimeError("demonstration did not cover all five mechanisms")
    transcript.append("【演示结束后的独立统计】\n" + json.dumps({
        "purchase": {"completed": sum(map(sum, env.lives)), "days": env.game.days_played},
        **env.game.mechanism_scores(),
    }, ensure_ascii=False, indent=2))
    return "\n\n".join(transcript), env


def main():
    print(demonstration()[0])


if __name__ == "__main__":
    main()
