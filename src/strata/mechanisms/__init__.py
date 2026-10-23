"""新机制（玩法 A）挂在这里：传闻、指称订单、改主意、前瞻任务、干扰信息……

每个机制是一个对象，挂到 Game(mechanisms=[...])、play(..., mechanisms=[...]) 或 Env(..., mechanisms=[...]) 上。
Game 每天在两个固定的时刻调它：

  order(game, want) -> want   订单刚生成、还没说出来。可以改订单（指称订单、改主意、前瞻任务）。
  news(game)                  当天的订单和摊子说完、拿主意之前。可以用 game.say(种类, ...) 加几句话
                              （传闻、干扰信息）；新的种类要在世界观的 [lines] 里加一行台词。

能用到的状态：game.world（真值，机制可以看）、game.here、game.want、game.life、game.log、game.say。

约定：
  机制要用随机数就自己开一个，比如 random.Random(f"{seed}:rumor")，不要动 world.rng 和 game.orders，
  否则开不开机制，同一个 seed 的世界和订单就不一样了，没法对照。
  需要别的时刻（比如过秤之后）就在 Game.run() 里加一个，并在这里写清楚。
"""


class Mechanism:
    """什么都不做的机制，新机制继承它，只改用得到的那个时刻。"""

    name = ""

    def order(self, game, want: dict) -> dict:
        return want

    def news(self, game) -> None:
        pass


__all__ = ["Mechanism"]
