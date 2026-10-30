"""世界观：只在显示边界把世界节点编号翻成名字，把事件写成文字。"""


class View:
    def __init__(self, view: dict, world):
        self.world = world
        self.lines, self.intro = view["lines"], view["intro"]
        self.pools = {"region": view["regions"], "village": view["villages"], "person": view["people"]}
        self.names = {k: {} for k in self.pools}
        self.regions = [n for n, d in enumerate(world.depth) if d == 0]
        self._indices = {n: i for nodes in (self.regions, world.villages) for i, n in enumerate(nodes)}

    def name(self, n: int) -> str:
        """输入统一为节点编号；人名按节点固定，地区和村按地图顺序起名。"""
        kind = ("region", "village", "person")[self.world.depth[n]]
        names, pool = self.names[kind], self.pools[kind]
        if n not in names:
            index = n if kind == "person" else self._indices[n]
            names[n] = pool[index % len(pool)] + (str(index // len(pool) + 1) if index >= len(pool) else "")
        return names[n]

    def map(self) -> str:
        """哪个地区有哪些村。"""
        places = []
        for r in self.regions:
            villages = [self.name(v) for v in self.world.villages if self.world.parent[v] == r]
            places.append(self.name(r) + "：" + "、".join(villages))
        return self.lines["map"].format(map="；".join(places))

    def say(self, kind: str, **kw) -> str:
        if kind == "stalls":
            return "，".join(self.lines["stall"].format(person=self.name(p), **seen)
                            for p, seen in kw["stalls"].items()) + "。"
        for k in ("village", "person"):
            if k in kw:
                kw[k] = self.name(kw[k])
        return self.lines[kind].format(**kw)
