"""dsh 的常驻文本环境进程。stdin 每行一个 {"action": "..."}，stdout 每行一个公开结果。

真值与内部事件只写 --log 指定的评测文件，不通过模型工具返回。死亡由这里直接续到下一世。
"""

import argparse
import json
import sys
from pathlib import Path

from strata import Env, load


class Episode:
    def __init__(self, cfg, seed, log):
        self.env = Env(cfg, seed=seed)
        self.log = log
        feedback = self.env.reset()
        self.protocol = "part-a-v2" if self.env.game.mechanisms else "daily-orders-v2"
        self.record("start", feedback=feedback, protocol=self.protocol, config=self.env.cfg,
                    mechanism_events=self.env.game.audit[:])
        self.initial = self.public(feedback) | {"instructions": self.env.instructions, "game": self.env.cfg["game"],
                                               "mechanism_config": self.env.cfg.get("mechanisms", {})}

    def record(self, kind, **data):
        self.log.write(json.dumps({"kind": kind, **data, "truth": self.env.truth()}, ensure_ascii=False) + "\n")
        self.log.flush()

    def public(self, feedback, parse_ok=True):
        return {"feedback": feedback, "observation": self.env.observation(), "done": self.env.done,
                "parse_ok": parse_ok, "lives": self.env.lives, "life": self.env.game.life,
                "day": self.env.world.day, "days_played": self.env.game.days_played, "protocol": self.protocol,
                **({"mechanism_scores": self.env.game.mechanism_scores()} if self.env.done else {})}

    def step(self, action):
        if not isinstance(action, str):
            raise TypeError("action must be a string")
        feedback, _, info = self.env.step(action)
        self.record("step", action=action, feedback=feedback, info=info)
        parse_ok = info["parse_ok"]
        if self.env.life_ended:
            rebirth, _, continued = self.env.step("继续")
            self.record("continue", action="继续", feedback=rebirth, info=continued)
            feedback += "\n" + rebirth
        return self.public(feedback, parse_ok)


def main():
    # JSONL 是 UTF-8；不随 Windows 控制台代码页变化。
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--log", type=Path, required=True)
    args = ap.parse_args()
    cfg = load(args.config)
    with args.log.open("x", encoding="utf-8") as log:
        try:
            episode = Episode(cfg, args.seed, log)
        except ValueError as error:
            ap.error(str(error))
        print(json.dumps(episode.initial, ensure_ascii=False), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if set(request) != {"action"}:
                    raise ValueError("only an action field is accepted")
                response = episode.step(request["action"])
            except (ValueError, TypeError, RuntimeError) as error:
                response = {"error": str(error)}
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
