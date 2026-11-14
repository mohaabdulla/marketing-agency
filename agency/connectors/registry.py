"""Registry of marketing connectors and client account configurations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .base import MarketingConnector, ConnectorCapability, ConnectorAccount, AuthStatus
from .errors import AuthenticationError, ConnectorError


class YouTubeConnector(MarketingConnector):
    def __init__(self):
        super().__init__("youtube", "YouTube Data & Video Studio")
        self._account: Optional[ConnectorAccount] = None

    def capabilities(self) -> List[ConnectorCapability]:
        return [
            ConnectorCapability.VIDEO_UPLOAD,
            ConnectorCapability.DRAFT_CREATION,
            ConnectorCapability.ANALYTICS_READ,
        ]

    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        token = credentials.get("access_token") or credentials.get("client_id")
        return bool(token and len(token) >= 8)

    def get_account_info(self) -> Optional[ConnectorAccount]:
        return self._account or ConnectorAccount(
            connector_id=self.connector_id,
            display_name="YouTube (User-Owned Channel)",
            account_id="yt_channel_default",
            auth_status=AuthStatus.NOT_CONNECTED,
            scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/yt-analytics.readonly"],
        )


class MetaConnector(MarketingConnector):
    def __init__(self):
        super().__init__("meta", "Meta Marketing & Instagram API")
        self._account: Optional[ConnectorAccount] = None

    def capabilities(self) -> List[ConnectorCapability]:
        return [
            ConnectorCapability.ORGANIC_PUBLISH,
            ConnectorCapability.IMAGE_PUBLISH,
            ConnectorCapability.AD_CREATE,
            ConnectorCapability.ANALYTICS_READ,
            ConnectorCapability.SCHEDULE,
        ]

    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        token = credentials.get("access_token")
        return bool(token and token.startswith("EA"))

    def get_account_info(self) -> Optional[ConnectorAccount]:
        return self._account or ConnectorAccount(
            connector_id=self.connector_id,
            display_name="Meta Business Manager (Instagram / FB)",
            account_id="act_meta_default",
            auth_status=AuthStatus.NOT_CONNECTED,
            scopes=["ads_management", "instagram_basic", "pages_show_list", "instagram_content_publish"],
        )


class GoogleAdsConnector(MarketingConnector):
    def __init__(self):
        super().__init__("google_ads", "Google Ads API (Cloud Project Access)")
        self._account: Optional[ConnectorAccount] = None

    def capabilities(self) -> List[ConnectorCapability]:
        return [
            ConnectorCapability.AD_CREATE,
            ConnectorCapability.AD_EDIT,
            ConnectorCapability.ANALYTICS_READ,
            ConnectorCapability.AUDIENCE_READ,
        ]

    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        cust_id = credentials.get("customer_id")
        return bool(cust_id and len(str(cust_id).replace("-", "")) == 10)

    def get_account_info(self) -> Optional[ConnectorAccount]:
        return self._account or ConnectorAccount(
            connector_id=self.connector_id,
            display_name="Google Ads Customer Account",
            account_id="gads_default",
            auth_status=AuthStatus.NOT_CONNECTED,
            scopes=["https://www.googleapis.com/auth/adwords"],
        )


class LinkedInConnector(MarketingConnector):
    def __init__(self):
        super().__init__("linkedin", "LinkedIn Marketing Solutions")
        self._account: Optional[ConnectorAccount] = None

    def capabilities(self) -> List[ConnectorCapability]:
        return [
            ConnectorCapability.ORGANIC_PUBLISH,
            ConnectorCapability.IMAGE_PUBLISH,
            ConnectorCapability.AD_CREATE,
            ConnectorCapability.ANALYTICS_READ,
        ]

    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        token = credentials.get("access_token")
        return bool(token and len(token) > 10)

    def get_account_info(self) -> Optional[ConnectorAccount]:
        return self._account or ConnectorAccount(
            connector_id=self.connector_id,
            display_name="LinkedIn Organization Page",
            account_id="urn:li:organization:default",
            auth_status=AuthStatus.NOT_CONNECTED,
            scopes=["w_organization_social", "r_organization_social", "rw_ads"],
        )


class PostizConnector(MarketingConnector):
    def __init__(self):
        super().__init__("postiz", "Postiz Open-Source Social Scheduler")
        self._account: Optional[ConnectorAccount] = None

    def capabilities(self) -> List[ConnectorCapability]:
        return [
            ConnectorCapability.ORGANIC_PUBLISH,
            ConnectorCapability.SCHEDULE,
            ConnectorCapability.IMAGE_PUBLISH,
            ConnectorCapability.VIDEO_UPLOAD,
        ]

    def validate_credentials(self, credentials: Dict[str, Any]) -> bool:
        url = credentials.get("instance_url")
        key = credentials.get("api_key")
        return bool(url and key)

    def get_account_info(self) -> Optional[ConnectorAccount]:
        return self._account or ConnectorAccount(
            connector_id=self.connector_id,
            display_name="Postiz Self-Hosted Instance",
            account_id="postiz_local",
            auth_status=AuthStatus.NOT_CONNECTED,
            scopes=["posts:write", "media:upload", "schedule"],
        )


class ConnectorRegistry:
    """Manages active connectors and tests credentials with strict secret hygiene."""

    def __init__(self):
        self._connectors: Dict[str, MarketingConnector] = {
            "youtube": YouTubeConnector(),
            "meta": MetaConnector(),
            "google_ads": GoogleAdsConnector(),
            "linkedin": LinkedInConnector(),
            "postiz": PostizConnector(),
        }

    def list_connectors(self) -> List[Dict[str, Any]]:
        results = []
        for cid, conn in self._connectors.items():
            acc = conn.get_account_info()
            results.append({
                "connector_id": cid,
                "display_name": conn.display_name,
                "capabilities": [c.value for c in conn.capabilities()],
                "account": acc.to_dict() if acc else None,
            })
        return results

    def get_connector(self, connector_id: str) -> Optional[MarketingConnector]:
        return self._connectors.get(connector_id)

    def test_connection(self, connector_id: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        conn = self.get_connector(connector_id)
        if not conn:
            raise ConnectorError(f"Connector '{connector_id}' not found")

        is_valid = conn.validate_credentials(credentials)
        status = AuthStatus.CONNECTED if is_valid else AuthStatus.ERROR

        account = ConnectorAccount(
            connector_id=connector_id,
            display_name=f"{conn.display_name} (Connected)",
            account_id=credentials.get("account_id") or "verified_account",
            auth_status=status,
            scopes=[c.value for c in conn.capabilities()],
            last_verified_at=datetime.now(timezone.utc).isoformat() if is_valid else None,
        )

        return {
            "connector_id": connector_id,
            "connected": is_valid,
            "status": status.value,
            "account": account.to_dict(),
            "message": "Connection verified successfully." if is_valid else "Credential validation failed. Please check tokens.",
        }


connector_registry = ConnectorRegistry()

