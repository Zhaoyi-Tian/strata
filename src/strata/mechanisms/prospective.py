"""到达后主动传话；不提醒、不自动完成，独立于采购计分。"""

import unicodedata
from copy import deepcopy

from . import Mechanism, integer, probability


def normalize(message):
    return "".join(c for c in unicodedata.normalize("NFKC", message)
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


class Prospective(Mechanism):
    name = "prospective"

    def __init__(self, rate=0.15, max_pending=2):
        self.rate = probability(rate, "prospective.rate")
        self.max_pending = integer(max_pending, "prospective.max_pending", 1)

    def reset(self, game):
        self.tasks, self.attempts = [], []

    def on(self, game, kind, **kw):
        if kind == "news":
            self.news(game)
        elif kind in ("arrive", "life_start"):
            self.arrive(game)
        elif kind in ("settled", "depart"):
            self.close_windows(game)

    def news(self, game):
        rng, w = self.rng(game, game.world.day, "news"), game.world
        if sum(t["status"] in ("pending", "open") for t in self.tasks) >= self.max_pending or rng.random() >= self.rate:
            return
        candidates = [p for p in w.people if w.parent[p] != game.here]
        if not candidates:
            return
        recipient = rng.choice(candidates)
        messages = [text for text in game.cfg["view"]["mechanism_text"]["messages"]
                    if not any(t["recipient"] == recipient and normalize(t["message"]) == normalize(text) for t in self.tasks)]
        if not messages:
            return
        self.issue(game, rng.choice(w.residents[game.here]), recipient, rng.choice(messages))

    def issue(self, game, speaker, recipient, message):
        """同样供受控演示使用；不修改世界或另开剧情结算逻辑。"""
        task = {"id": f"task:{game.world.day}:{len(self.tasks) + 1}", "speaker": speaker, "recipient": recipient,
                "village": game.world.parent[recipient], "message": message, "created_day": game.world.day,
                "status": "pending", "opportunity_day": None}
        self.tasks.append(task)
        game.record("task_issued", **task)
        game.emit("commission", speaker=speaker, person=recipient, village=task["village"], message=message)
        return task

    def arrive(self, game):
        for task in self.tasks:
            if task["status"] == "pending" and task["village"] == game.here:
                task.update(status="open", opportunity_day=game.world.day)
                game.record("task_opportunity", task_id=task["id"], village=game.here)

    def deliver(self, game, person, message):
        matching = [t for t in self.tasks if t["status"] == "open" and t["recipient"] == person
                    and normalize(t["message"]) == normalize(message)]
        previous = any(t["status"] == "completed" and t["recipient"] == person
                       and normalize(t["message"]) == normalize(message) for t in self.tasks)
        result = "completed" if matching else "duplicate" if previous else "incorrect"
        for task in matching:
            task.update(status="completed", completed_day=game.world.day)
        attempt = {"person": person, "message": message, "result": result,
                   "task_ids": [t["id"] for t in matching], "day": game.world.day}
        self.attempts.append(attempt)
        game.record("message_delivered", **attempt)
        # 所有有效传话反馈一致，不能拿 NPC 当口信答案探测器。
        game.emit("message_delivered", person=person)

    def close_windows(self, game):
        for task in self.tasks:
            if task["status"] == "open":
                task.update(status="missed", closed_day=game.world.day)
                game.record("task_missed", task_id=task["id"])

    def metrics(self):
        opportunities = sum(t["opportunity_day"] is not None for t in self.tasks)
        completed = sum(t["status"] == "completed" for t in self.tasks)
        return {"issued": len(self.tasks), "opportunities": opportunities, "completed": completed,
                "missed": sum(t["status"] == "missed" for t in self.tasks),
                "untriggered": sum(t["status"] == "pending" for t in self.tasks),
                "incorrect": sum(a["result"] == "incorrect" for a in self.attempts),
                "duplicates": sum(a["result"] == "duplicate" for a in self.attempts),
                "completion_rate": completed / opportunities if opportunities else None}

    def snapshot(self):
        return {"tasks": deepcopy(self.tasks), "metrics": self.metrics()}
