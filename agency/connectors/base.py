"""Base marketing connector interface and capabilities definition."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ConnectorCapability(str, Enum):
    ORGANIC_PUBLISH = "organic_publish"
    VIDEO_UPLOAD = "video_upload"
    IMAGE_PUBLISH = "image_publish"
    DRAFT_CREATION = "draft_creation"
    AD_CREATE = "ad_create"
    AD_EDIT = "ad_edit"
    ANALYTICS_READ = "analytics_read"
    SCHEDULE = "schedule"
    COMMENTS_READ = "comments_read"
    AUDIENCE_READ = "audience_read"


class AuthStatus(str, Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class ConnectorAccount:
    connector_id: str
    display_name: str
    account_id: str
    auth_status: AuthStatus = AuthStatus.NOT_CONNECTED
    scopes: List[str] = field(default_factory=list)
    last_verified_at: Optional[str] = None
    rate_limit_remaining: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["auth_status"] = self.auth_status.value
        return d


class MarketingConnector(ABC):
    """Abstract base class for all user-owned marketing platform adapters."""

    def __init__(self, connector_id: str, display_name: str):
        self.connector_id = connector_id
        self.display_name = display_name

    @abstractmethod
    def capabilities(self) -> List[ConnectorCapability]:
        """Declare explicit operations supported by this connector."""
        pass

    @abstractmethod
    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        """Check whether user-supplied credentials are valid."""
        pass

    @abstractmethod
    def get_account_info(self) -> Optional[ConnectorAccount]:
        """Return connected account metadata with secret masking."""
        pass

    def create_draft(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.display_name} does not support draft creation.")

    def publish(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.display_name} does not support direct publishing.")

    def fetch_metrics(self, campaign_id: str, date_range: Dict[str, str]) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.display_name} does not support metrics retrieval.")

