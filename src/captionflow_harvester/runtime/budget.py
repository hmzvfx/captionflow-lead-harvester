from __future__ import annotations

import threading
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class RequestBudget:
    limits: dict[str, int]
    counters: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remaining(self, name: str) -> int:
        limit = self.limits.get(name, 0)
        return max(0, limit - self.counters.get(name, 0))

    def try_consume(self, name: str, amount: int = 1) -> bool:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with self._lock:
            limit = self.limits.get(name, 0)
            current = self.counters.get(name, 0)
            if current + amount > limit:
                return False
            self.counters[name] = current + amount
            return True

    def consume(self, name: str, amount: int = 1) -> None:
        if not self.try_consume(name, amount):
            raise BudgetExceeded(f"budget exhausted: {name}")
