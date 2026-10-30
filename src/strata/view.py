"""世界观：给骨架起名字，把每天发生的事写成文字。内容来自 config/worldview.toml。"""


class View:
    def __init__(self, view: dict):
        self.lines, self.intro = view["lines"], view["intro"]
        self.pools = {"region": view["regions"], "village": view["villages"], "person": view["people"]}
        self.names = {k: {} for k in self.pools}

    def name(self, kind, n) -> str:
        """都按编号起名，人物使用世界节点编号；名字不够用时自动加编号。"""
        names, pool = self.names[kind], self.pools[kind]
        if n not in names:
            names[n] = pool[n % len(pool)] + (str(n // len(pool) + 1) if n >= len(pool) else "")
        return names[n]

    def find(self, kind, name):
        """按名字找回编号；没这个名字就是 None。"""
        if kind == "village" and name in self.pools["village"]:
            return self.pools["village"].index(name)
        return next((n for n, x in self.names[kind].items() if x == name), None)

    def map(self, size) -> str:
        """哪个地区有哪些村。"""
        regions, k, _ = size
        places = "；".join(self.name("region", r) + "：" + "、".join(self.name("village", r * k + v) for v in range(k))
                          for r in range(regions))
        return self.lines["map"].format(map=places)

    def say(self, kind: str, **kw) -> str:
        if kind == "stalls":
            return "，".join(self.lines["stall"].format(person=self.name("person", p), **seen)
                            for p, seen in kw["stalls"].items()) + "。"
        for k in ("village", "person"):
            if k in kw:
                kw[k] = self.name(k, kw[k])
        return self.lines[kind].format(**kw)
