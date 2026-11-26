"""世界观：只在显示边界把世界节点编号翻成名字，把事件写成文字。"""


class View:
    def __init__(self, view: dict, world):
        self.world = world
        self.lines, self.intro = view["lines"], view["intro"]
        self.visible = [s["name"] for s in view["slots"] if s["visible"]]
        self.claims = view.get("mechanism_text", {}).get("claims", {})
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
        if kind == "rumor":
            kw["claim"] = self.claims.get(kw["slot"], "在‘{slot}’这件事上是{value}").format(**kw)
        if kind == "revision" and kw["reference"] is None:
            kind = "revision_open"
        if "reference" in kw:
            kw["reference"] = self.reference(kw["reference"]) if kw["reference"] else "任一符合要求的人"
        if "want" in kw:
            want = kw.pop("want")
            kw["goods"] = "、".join(v for s, v in want.items() if s in self.visible)
            kw["conditions"] = "、".join(v for s, v in want.items() if s not in self.visible)
        if kind == "wrong_person":
            kw["goods"] = "、".join(kw["goods"].values())
            kw["traits"] = "、".join(f"{s}：{v}" for s, v in kw["traits"].items())
        for k in ("village", "person", "speaker"):
            if k in kw:
                kw[k] = self.name(kw[k])
        return self.lines[kind].format(**kw)

    def reference(self, reference):
        """只渲染公开指称，不查询世界或内部正确人选。"""
        kind = "reference_transaction" if reference["kind"] == "transaction" else "reference_previous"
        return self.lines[kind].format(**reference)
