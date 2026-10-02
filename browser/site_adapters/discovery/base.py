from abc import ABC, abstractmethod
from typing import Any, List, Optional
from shared.contracts.models import NormalizedJob


class JobSourceAdapter(ABC):
    """
    Abstract interface for job source discovery connectors.
    New job sources can be added without modifying the matching engine.
    """
    @property
    @abstractmethod
    def source_name(self) -> str:
        """The source identifier e.g. 'workable', 'greenhouse', 'lever'."""
        pass

    @abstractmethod
    async def discover_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> List[NormalizedJob]:
        """Discovers public jobs, returning a normalized job model for each."""
        pass
