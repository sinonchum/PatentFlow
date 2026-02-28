import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class OAuthToken:
    access_token: str
    token_type: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class EPOClient:
    def __init__(
        self,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        *,
        enabled: Optional[bool] = None,
        token_url: str = "https://ops.epo.org/3.2/auth/accesstoken",
        base_url: str = "https://ops.epo.org/3.2/rest-services",
        timeout: int = 30,
    ) -> None:
        load_dotenv(override=False)

        self.enabled = _env_flag("EPO_ENABLED", True) if enabled is None else enabled

        self.consumer_key = consumer_key or os.getenv("EPO_CONSUMER_KEY")
        self.consumer_secret = consumer_secret or os.getenv("EPO_CONSUMER_SECRET")

        if not self.consumer_key or not self.consumer_secret:
            self.enabled = False

        self.token_url = token_url
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self._session = requests.Session()
        self._token: Optional[OAuthToken] = None

    def _fetch_token(self) -> OAuthToken:
        if not self.enabled:
            raise RuntimeError(
                "EPO client is disabled. Set EPO_ENABLED=true and configure EPO_CONSUMER_KEY/EPO_CONSUMER_SECRET."
            )

        resp = self._session.post(
            self.token_url,
            data={"grant_type": "client_credentials"},
            auth=(self.consumer_key, self.consumer_secret),
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()

        access_token = payload["access_token"]
        token_type = payload.get("token_type", "Bearer")
        expires_in = int(payload.get("expires_in", 1200))
        expires_at = time.time() + max(0, expires_in - 30)

        return OAuthToken(access_token=access_token, token_type=token_type, expires_at=expires_at)

    def _get_valid_token(self) -> OAuthToken:
        if not self.enabled:
            raise RuntimeError(
                "EPO client is disabled. Set EPO_ENABLED=true and configure EPO_CONSUMER_KEY/EPO_CONSUMER_SECRET."
            )

        if self._token is None or self._token.is_expired:
            self._token = self._fetch_token()
        return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        json: Any = None,
    ) -> requests.Response:
        if not self.enabled:
            raise RuntimeError(
                "EPO client is disabled (missing credentials or EPO_ENABLED=false). Configure EPO credentials to use EPO requests."
            )

        token = self._get_valid_token()

        url = path
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"{self.base_url}/{path.lstrip('/')}"

        merged_headers: Dict[str, str] = {
            "Authorization": f"{token.token_type} {token.access_token}",
        }
        if headers:
            merged_headers.update(headers)

        resp = self._session.request(
            method=method.upper(),
            url=url,
            params=params,
            headers=merged_headers,
            data=data,
            json=json,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp
