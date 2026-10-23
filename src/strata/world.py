"""世界：只管规律。唯一的宗旨是宏观变得慢，微观变得快。参数见 config/default.toml 的 [world]。

固定三层：地区 → 村 → 人。每个节点有若干槽位（特质），每个槽位各自：
  继承：要么有自己的值，要么随上一层；最上层总有自己的值。
  重抽：有一个时钟，时钟响时，以概率 mu 换成自己的一个值，否则改回随上一层。
快慢：人的时钟平均隔 tau ~ tau·ratio 天响一次，村再慢 ratio 倍，地区再慢 ratio 倍；具体落在哪，因节点而异。
真值可追溯：任何时刻都能查到一个值由哪个节点决定（source），以及它上次变是哪天（since）。只给评测用，不影响规律。
"""

import random


class World:
    def __init__(self, seed, slots: dict, size, tau, ratio, mu):
        """slots：槽位名 -> 取值列表；size：地区数、每个地区几个村、每个村几个人。"""
        self.rng = random.Random(seed)
        self.slots = {k: tuple(v) for k, v in slots.items()}
        self.mu, self.parent, self.depth = mu, [], []
        regions, villages, people = size
        for _ in range(regions):
            r = self._add(None)
            for _ in range(villages):
                v = self._add(r)
                for _ in range(people):
                    self._add(v)
        nodes = range(len(self.depth))
        # 每个（节点，槽位）的平均变化间隔：落在 tau·ratio^k 到 tau·ratio^(k+1) 之间，k 是离最下层几层
        self.tau = {s: [tau * ratio ** (2 - self.depth[n] + self.rng.random()) for n in nodes] for s in self.slots}
        self.own = {s: [self._draw(n, s) for n in nodes] for s in self.slots}
        self.villages = [n for n in nodes if self.depth[n] == 1]
        self.people = [n for n in nodes if self.depth[n] == 2]
        self.residents = {v: [p for p in self.people if self.parent[p] == v] for v in self.villages}
        self.below = {n: [n] for n in nodes}                    # 每个节点连同它下面的所有节点
        for n in reversed(nodes):                               # 下层的编号总比上层大，所以倒着收
            if self.parent[n] is not None:
                self.below[self.parent[n]] += self.below[n]
        self.since = {s: [0] * len(nodes) for s in self.slots}  # 每个节点在每个槽位上表现出来的值，上次变是哪天
        self.day = 0

    def _add(self, parent) -> int:
        self.parent.append(parent)
        self.depth.append(0 if parent is None else self.depth[parent] + 1)
        return len(self.depth) - 1

    def _draw(self, n, s):
        """最上层总有自己的值；其余以概率 mu 有自己的值，否则随上一层（None）。"""
        if self.depth[n] == 0 or self.rng.random() < self.mu:
            return self.rng.choice(self.slots[s])
        return None

    def source(self, n, s) -> int:
        """n 在槽位 s 上表现出来的值由哪个节点决定：从 n 往上数，第一个有自己值的。"""
        own = self.own[s]
        while own[n] is None:
            n = self.parent[n]
        return n

    def value(self, n, s) -> str:
        return self.own[s][self.source(n, s)]

    def step(self):
        """过一天：每个（节点，槽位）的时钟以 1/τ 的概率响一次。顺手记下谁表现出来的值变了。"""
        self.day += 1
        for s, taus in self.tau.items():
            for n, t in enumerate(taus):
                if self.rng.random() < 1 / t:
                    before = [self.value(m, s) for m in self.below[n]]
                    self.own[s][n] = self._draw(n, s)
                    for m, v in zip(self.below[n], before, strict=True):
                        if self.value(m, s) != v:
                            self.since[s][m] = self.day

    def chain(self, n) -> list[int]:
        """从最上层到 n 的一串节点。"""
        out = [n]
        while self.parent[out[-1]] is not None:
            out.append(self.parent[out[-1]])
        return out[::-1]

    def distance(self, a, b) -> int:
        """从村 a 到村 b 路上走几天：同一地区里串村当天就到，去别的地区走一天。"""
        return 0 if self.parent[a] == self.parent[b] else 1
