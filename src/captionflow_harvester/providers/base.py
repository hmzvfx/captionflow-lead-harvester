from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import Config
from ..models import Candidate
from ..persistence.state import StateStore
from ..runtime.budget import RequestBudget
from ..runtime.metrics import RunMetrics
from ..runtime.network import AsyncHttpClient


@dataclass
class ProviderContext:
    config: Config
    budget: RequestBudget
    http: AsyncHttpClient
    state: StateStore
    metrics: RunMetrics


class DiscoveryProvider(ABC):
    name = "BASE"

    def __init__(self, context: ProviderContext) -> None:
        self.context = context

    @abstractmethod
    async def discover(self) -> list[Candidate]:
        raise NotImplementedError
