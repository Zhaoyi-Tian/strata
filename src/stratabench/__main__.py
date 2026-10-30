"""stratabench [--config 文件] [--seeds N] [--show 行数]：几种采办在同样的世界里各玩一局，看每一世平均每天做成几单。"""

import argparse

from strata import Game, View, load, play

from .agents import AGENTS, Inference


def main():
    ap = argparse.ArgumentParser(prog="stratabench", description=__doc__)
    ap.add_argument("--config")
    ap.add_argument("--seeds", type=int, default=5, help="对几个世界取平均")
    ap.add_argument("--show", type=int, default=12, help="打印分层推断那一局的前几行")
    ap.add_argument("--early", type=int, default=20, help="重生后头几天单独统计")
    a = ap.parse_args()
    cfg = load(a.config)
    g = cfg["game"]

    game = Game(cfg)
    view, printed = View(cfg["view"], game.world), []

    def say(kind, **kw):
        if len(printed) < a.show:
            printed.append(view.say(kind, **kw))

    print(cfg["view"]["intro"], view.map(), "", sep="\n")
    game.say = say
    game.play(Inference)
    print("\n".join(printed), "\n")

    print(f"{a.seeds} 个世界的平均。{g['lives']} 世，每世 {g['life']} 天，死后空转 {g['gap']} 天。"
          f"每天成单率（路上的天算没成）；「重生头 {a.early} 天」是第二世起的平均\n")
    print(f"{'':>8}" + "".join(f"{f'第 {i} 世':>8}" for i in range(1, g["lives"] + 1)) + f"  重生头 {a.early} 天")
    for make in AGENTS:
        per_life, early = [0.0] * g["lives"], []
        for seed in range(g["seed"], g["seed"] + a.seeds):
            lives = play({**cfg, "game": {**g, "seed": seed}}, make)
            per_life = [x + sum(log) / len(log) / a.seeds for x, log in zip(per_life, lives, strict=True)]
            early += [x for log in lives[1:] for x in log[:a.early]]
        print(f"{make.name:>8}" + "".join(f"{x:>10.0%}" for x in per_life) + f"{sum(early) / len(early):>12.0%}")


if __name__ == "__main__":
    main()
