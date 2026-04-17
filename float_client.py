"""Async HTTP client for Float.com API with session caching.

Implements the same 4-step authentication flow as the Go CLI:
1. GET /login -> extract CSRF token from HTML
2. POST /login -> submit credentials with CSRF token
3. GET /me-api -> get company/account IDs, generate notify-uuid
4. GET /getJWToken -> obtain short-lived JWT

Session caching strategy (3 tiers):
1. Reuse cached JWT if not expired (0 HTTP calls)
2. Refresh JWT using cached session cookie (1 HTTP call)
3. Full login if everything expired (4 HTTP calls)
"""

import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from config import get_base_url, get_email, get_password, get_session_cache_path
from models import LoggedTime, Project, SessionCache, TimeEntryInput

logger = logging.getLogger(__name__)


class FloatClientError(Exception):
    """Raised when a Float API call fails."""


class FloatAuthError(FloatClientError):
    """Raised when authentication fails."""


class FloatClient:
    """Async HTTP client for the Float.com web API."""

    def __init__(self) -> None:
        self._base_url = get_base_url()
        self._email = get_email()
        self._password = get_password()
        self._session_cache_path = get_session_cache_path()

        self._jwt_token: str = ""
        self._jwt_expiry: int = 0
        self._notify_uuid: str = ""
        self._people_id: int = 0
        self._account_name: str = ""
        self._company_name: str = ""

        # httpx async client with cookie persistence
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Session info (populated after login) ────────────────────────

    @property
    def people_id(self) -> int:
        """The authenticated user's people ID (extracted from JWT)."""
        return self._people_id

    @property
    def account_name(self) -> str:
        """The authenticated user's display name."""
        return self._account_name

    @property
    def company_name(self) -> str:
        """The authenticated user's company name."""
        return self._company_name

    # ── Authentication ──────────────────────────────────────────────

    async def login(self) -> None:
        """Authenticate using cached session or full login flow.

        Strategy:
        1. If cached JWT is still valid (not expired) -> use it (0 HTTP calls)
        2. If cached session cookie is still valid -> refresh JWT (1 HTTP call)
        3. Otherwise -> full login flow (4 HTTP calls) and cache the session
        """
        cached = self._load_session()

        if cached is not None:
            now = int(time.time())

            # Strategy 1: JWT still valid (with 60s safety margin)
            if cached.jwt_token and cached.jwt_expiry > now + 60 and cached.notify_uuid:
                self._jwt_token = cached.jwt_token
                self._jwt_expiry = cached.jwt_expiry
                self._notify_uuid = cached.notify_uuid
                self._people_id = cached.people_id
                self._account_name = cached.account_name
                self._company_name = cached.company_name
                # If people_id wasn't in the cache (old format), decode from JWT
                if not self._people_id:
                    self._decode_jwt_payload()
                logger.info("Using cached JWT token (still valid)")
                return

            # Strategy 2: Session cookie still valid, refresh JWT only
            if cached.session_cookie and cached.session_expiry:
                try:
                    session_exp = datetime.fromisoformat(cached.session_expiry)
                    if session_exp > datetime.now(timezone.utc):
                        logger.info(
                            "Cached JWT expired, refreshing using session cookie..."
                        )
                        self._restore_session_cookies(cached)
                        self._notify_uuid = cached.notify_uuid

                        try:
                            await self._fetch_jwt_token()
                            self._decode_jwt_payload()
                            logger.info("Refreshed JWT token successfully")
                            self._save_session()
                            return
                        except FloatClientError:
                            logger.info(
                                "JWT refresh failed, falling back to full login"
                            )
                except ValueError:
                    pass

        # Strategy 3: Full login flow
        await self._full_login()

    async def _full_login(self) -> None:
        """Perform the complete 4-step login flow and cache the session."""
        logger.info("Starting full login flow...")

        # Step 1: GET /login to get CSRF token and cookies
        csrf_token = await self._fetch_csrf_token()
        logger.info("Got CSRF token: %s...", csrf_token[:20])

        # Step 2: POST /login with credentials
        await self._submit_login(csrf_token)
        logger.info("Login successful")

        # Step 3: GET /me-api to build notify-uuid
        await self._fetch_notify_uuid()
        logger.info("Generated notify-uuid: %s", self._notify_uuid)

        # Step 4: GET /getJWToken to get JWT
        await self._fetch_jwt_token()
        self._decode_jwt_payload()
        logger.info("Got JWT token: %s...", self._jwt_token[:40])
        logger.info(
            "Logged in as %s (people_id=%d, company=%s)",
            self._account_name,
            self._people_id,
            self._company_name,
        )

        # Cache the session
        self._save_session()

    async def _fetch_csrf_token(self) -> str:
        """GET /login and extract the CSRF token from the HTML."""
        resp = await self._client.get(f"{self._base_url}/login")
        resp.raise_for_status()

        match = re.search(r'csrf-token" content="([^"]+)"', resp.text)
        if not match:
            raise FloatAuthError("CSRF token not found in login page")

        return match.group(1)

    async def _submit_login(self, csrf_token: str) -> None:
        """POST /login with credentials and CSRF token."""
        data = {
            "_csrf": csrf_token,
            "LoginForm[email]": self._email,
            "LoginForm[password]": self._password,
        }

        resp = await self._client.post(
            f"{self._base_url}/login",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self._base_url,
                "Referer": f"{self._base_url}/login",
            },
        )

        if resp.status_code != 302:
            body = resp.text
            if "locked due to multiple failed login attempts" in body:
                raise FloatAuthError(
                    "Account is locked due to multiple failed login attempts, "
                    "please try again in 5 minutes"
                )
            if "Incorrect email or password" in body or "error-message" in body:
                raise FloatAuthError("Login failed: incorrect email or password")
            raise FloatAuthError(
                f"Login failed: expected 302 redirect, got {resp.status_code}"
            )

    async def _fetch_notify_uuid(self) -> None:
        """GET /me-api to get company/account IDs and generate notify-uuid."""
        resp = await self._client.get(
            f"{self._base_url}/me-api",
            params={"expand": "managers", "json": "1"},
        )

        if resp.status_code != 200:
            raise FloatAuthError(
                f"me-api failed with status {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        cid = data.get("cid", 0)
        admin_id = data.get("admin_id", 0)

        if not cid or not admin_id:
            raise FloatAuthError(
                f"me-api returned invalid cid={cid} or admin_id={admin_id}"
            )

        random_uuid = str(uuid.uuid4())
        self._notify_uuid = f"{cid}-{admin_id}-{random_uuid}"

    async def _fetch_jwt_token(self) -> None:
        """GET /getJWToken to obtain the JWT access token."""
        resp = await self._client.get(f"{self._base_url}/getJWToken?")

        if resp.status_code != 200:
            raise FloatClientError(
                f"getJWToken failed with status {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        token_data = data.get("token", {})
        access_token = token_data.get("access_token", "")
        expiry = token_data.get("expiry", 0)

        if not access_token:
            raise FloatClientError("JWT access token is empty")

        self._jwt_token = access_token
        self._jwt_expiry = expiry

    def _decode_jwt_payload(self) -> None:
        """Decode the JWT payload to extract people_id and account info.

        JWT tokens are three base64url-encoded segments separated by dots.
        We only need the payload (middle segment) - no signature verification
        needed since the server already validated the token.
        """
        try:
            parts = self._jwt_token.split(".")
            if len(parts) != 3:
                logger.warning("JWT token does not have 3 parts, skipping decode")
                return

            # Base64url decode the payload (add padding)
            payload_b64 = parts[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)

            account = payload.get("account", {})
            self._people_id = account.get("people_id", 0)
            self._account_name = account.get("name", "")

            company = payload.get("company", {})
            self._company_name = company.get("name", "")
        except Exception as e:
            logger.warning("Failed to decode JWT payload: %s", e)

    # ── Session caching ─────────────────────────────────────────────

    def _load_session(self) -> SessionCache | None:
        """Load cached session from disk."""
        path = Path(self._session_cache_path)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            return SessionCache(**data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _save_session(self) -> None:
        """Save current session state to disk."""
        cached = SessionCache(
            jwt_token=self._jwt_token,
            jwt_expiry=self._jwt_expiry,
            notify_uuid=self._notify_uuid,
            people_id=self._people_id,
            account_name=self._account_name,
            company_name=self._company_name,
        )

        # Extract cookies from the httpx client
        for cookie in self._client.cookies.jar:
            if cookie.name == "float2sessprd":
                cached.session_cookie = cookie.value
                if cookie.expires:
                    cached.session_expiry = datetime.fromtimestamp(
                        cookie.expires, tz=timezone.utc
                    ).isoformat()
                else:
                    cached.session_expiry = (
                        datetime.now(timezone.utc) + timedelta(days=14)
                    ).isoformat()
            elif cookie.name == "_csrf":
                cached.csrf_cookie = cookie.value
            elif cookie.name == "GCLB":
                cached.gclb_cookie = cookie.value

        path = Path(self._session_cache_path)
        path.write_text(cached.model_dump_json(indent=2))
        # Restrict file permissions
        path.chmod(0o600)

    def _restore_session_cookies(self, cached: SessionCache) -> None:
        """Restore cached cookies into the httpx client."""
        if cached.session_cookie:
            self._client.cookies.set(
                "float2sessprd",
                cached.session_cookie,
                domain=".float.com",
                path="/",
            )
        if cached.csrf_cookie:
            self._client.cookies.set(
                "_csrf",
                cached.csrf_cookie,
                domain=".float.com",
                path="/",
            )
        if cached.gclb_cookie:
            self._client.cookies.set(
                "GCLB",
                cached.gclb_cookie,
                domain=".float.com",
                path="/",
            )

    # ── API headers ─────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Return headers required for authenticated API calls."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._jwt_token}",
            "X-Token-Type": "JWT",
            "notify-uuid": self._notify_uuid,
        }

    # ── API methods ─────────────────────────────────────────────────

    async def get_logged_time_entries(
        self, start_date: str, end_date: str
    ) -> list[LoggedTime]:
        """Fetch logged time entries for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.

        Returns:
            List of LoggedTime entries.
        """
        resp = await self._client.get(
            f"{self._base_url}/svc/api3/v3/logged-time",
            params={
                "lean": "1",
                "start_date": start_date,
                "end_date": end_date,
                "internal_pagination": "1",
            },
            headers=self._auth_headers(),
        )

        if resp.status_code != 200:
            raise FloatClientError(
                f"get logged time failed with status {resp.status_code}: {resp.text}"
            )

        return [LoggedTime(**entry) for entry in resp.json()]

    async def get_projects(self) -> list[Project]:
        """Fetch all projects with people assignment info.

        Returns:
            List of Project objects including people_ids.
        """
        resp = await self._client.get(
            f"{self._base_url}/svc/api3/v3/projects/all",
            params={"lean": "1", "expand": "people_ids"},
            headers=self._auth_headers(),
        )

        if resp.status_code != 200:
            raise FloatClientError(
                f"get projects failed with status {resp.status_code}: {resp.text}"
            )

        return [Project(**p) for p in resp.json()]

    async def get_my_projects(self) -> list[Project]:
        """Fetch projects assigned to the authenticated user.

        Filters all projects to only those where the user's people_id
        is in the project's people_ids list.

        Returns:
            List of Project objects the user can log time to.
        """
        all_projects = await self.get_projects()
        if not self._people_id:
            return all_projects
        return [p for p in all_projects if self._people_id in p.people_ids]

    async def create_time_entries(
        self, entries: list[TimeEntryInput]
    ) -> list[LoggedTime]:
        """Create one or more time entries.

        Args:
            entries: List of TimeEntryInput objects to create.

        Returns:
            List of created LoggedTime entries.
        """
        payload = [entry.model_dump() for entry in entries]

        logger.info("Sending %d time entries", len(payload))

        resp = await self._client.post(
            f"{self._base_url}/svc/api3/v3/logged-time",
            json=payload,
            headers=self._auth_headers(),
        )

        if resp.status_code not in (200, 201):
            raise FloatClientError(
                f"create time entry failed with status {resp.status_code}: {resp.text}"
            )

        return [LoggedTime(**entry) for entry in resp.json()]

    async def delete_time_entry(self, logged_time_id: str) -> None:
        """Delete a time entry by setting its hours to 0.

        Float's API uses PUT with hours=0 to remove a time entry,
        rather than a DELETE HTTP method.

        Args:
            logged_time_id: The logged_time_id of the entry to delete.
        """
        payload = [{"logged_time_id": logged_time_id, "hours": 0}]

        logger.info("Deleting time entry %s", logged_time_id)

        resp = await self._client.put(
            f"{self._base_url}/svc/api3/v3/logged-time/{logged_time_id}",
            json=payload,
            headers=self._auth_headers(),
        )

        if resp.status_code != 200:
            raise FloatClientError(
                f"delete time entry failed with status {resp.status_code}: {resp.text}"
            )
