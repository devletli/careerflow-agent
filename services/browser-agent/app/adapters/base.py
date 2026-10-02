"""SiteAdapter interface for application-site form automation."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from playwright.async_api import Page


@dataclass
class FillResult:
    filled: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)  # no verified profile data
    needs_human: List[str] = field(default_factory=list)  # captcha/login/open-ended
    submitted: bool = False


class SiteAdapter(ABC):
    """Per-site form-filling strategy. GenericAdapter always matches last."""

    name: str = "base"

    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool:
        """Whether this adapter handles the given application URL."""
        ...

    @abstractmethod
    async def fill(self, page: "Page", answers: Dict[str, Any]) -> FillResult:
        """Fills safe fields from verified answers. Never submits."""
        ...

    async def submit(self, page: "Page") -> bool:
        """Clicks the submit button. Only called in an explicitly confirmed flow."""
        raise NotImplementedError
