"""
GoHighLevel API V2 Client.

Tüm istekler https://services.leadconnectorhq.com üzerinden gider ve
zorunlu Version: 2021-07-28 header'ı ile yapılır. Sayfalama, retry ve
hata loglama içerir.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ghl")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"


class GHLAuthError(Exception):
    pass


class GHLAPIError(Exception):
    pass


@dataclass
class GHLConfig:
    api_key: str
    location_id: str

    @classmethod
    def from_env(cls) -> "GHLConfig":
        api_key = os.getenv("GOHIGHLEVEL_API_KEY")
        location_id = os.getenv("GOHIGHLEVEL_LOCATION_ID")
        if not api_key or not location_id:
            raise GHLAuthError(
                ".env içinde GOHIGHLEVEL_API_KEY veya GOHIGHLEVEL_LOCATION_ID eksik."
            )
        return cls(api_key=api_key, location_id=location_id)


class GHLClient:
    def __init__(self, config: GHLConfig | None = None, timeout: int = 30):
        self.config = config or GHLConfig.from_env()
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Version": API_VERSION,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    # ---------- low-level ----------
    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        retries: int = 2,
    ) -> dict:
        url = f"{BASE_URL}{path}"
        for attempt in range(retries + 1):
            try:
                r = self._session.request(
                    method, url, params=params, json=json_body, timeout=self.timeout
                )
                if r.status_code == 401:
                    raise GHLAuthError(f"401 Unauthorized: {r.text[:200]}")
                if r.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limit. %ss bekleniyor.", wait)
                    time.sleep(wait)
                    continue
                if r.status_code >= 400:
                    raise GHLAPIError(f"{r.status_code} {method} {path}: {r.text[:300]}")
                return r.json() if r.content else {}
            except requests.RequestException as e:
                if attempt == retries:
                    raise GHLAPIError(f"Network error: {e}") from e
                time.sleep(2 ** attempt)
        return {}

    # ---------- pipelines ----------
    def list_pipelines(self) -> list[dict]:
        data = self._request(
            "GET",
            "/opportunities/pipelines",
            params={"locationId": self.config.location_id},
        )
        return data.get("pipelines", [])

    # ---------- users (assigned-to lookup) ----------
    def list_users(self) -> list[dict]:
        data = self._request(
            "GET", "/users/", params={"locationId": self.config.location_id}
        )
        return data.get("users", [])

    # ---------- custom fields ----------
    def list_custom_fields(self) -> list[dict]:
        data = self._request(
            "GET",
            f"/locations/{self.config.location_id}/customFields",
        )
        return data.get("customFields", [])

    # ---------- opportunities ----------
    def search_opportunities(
        self,
        limit: int = 100,
        pipeline_id: str | None = None,
        status: str | None = None,
        start_after_id: str | None = None,
        start_after: int | None = None,
        date_after_ms: int | None = None,
        date_before_ms: int | None = None,
    ) -> dict:
        """V2 search.

        Tarih filtresi (server-side):
          date_after_ms  → createdAt >= ms  (API parametresi: `date`)
          date_before_ms → createdAt <= ms  (API parametresi: `endDate`)
        """
        params: dict[str, Any] = {
            "location_id": self.config.location_id,
            "limit": limit,
        }
        if pipeline_id:
            params["pipeline_id"] = pipeline_id
        if status:
            params["status"] = status
        if start_after_id:
            params["startAfterId"] = start_after_id
        if start_after:
            params["startAfter"] = start_after
        if date_after_ms is not None:
            params["date"] = int(date_after_ms)
        if date_before_ms is not None:
            params["endDate"] = int(date_before_ms)
        return self._request("GET", "/opportunities/search", params=params)

    def iter_all_opportunities(
        self,
        pipeline_id: str | None = None,
        status: str | None = None,
        page_size: int = 100,
        max_records: int = 2000,
        date_after_ms: int | None = None,
        date_before_ms: int | None = None,
    ) -> Iterable[dict]:
        """Sayfalama ile fırsatları döner. max_records güvenlik tavanı; tarih
        filtreleri server-side uygulanır (createdAt >= date_after_ms ve
        createdAt <= date_before_ms)."""
        start_after_id: str | None = None
        start_after: int | None = None
        seen = 0
        page = 0
        while seen < max_records:
            page += 1
            data = self.search_opportunities(
                limit=min(page_size, max_records - seen),
                pipeline_id=pipeline_id,
                status=status,
                start_after_id=start_after_id,
                start_after=start_after,
                date_after_ms=date_after_ms,
                date_before_ms=date_before_ms,
            )
            batch = data.get("opportunities", [])
            if not batch:
                break
            for o in batch:
                yield o
            seen += len(batch)
            meta = data.get("meta") or {}
            next_id = meta.get("startAfterId")
            next_after = meta.get("startAfter")
            if not next_id or not next_after:
                break
            if len(batch) < page_size:
                break
            start_after_id = next_id
            start_after = next_after
        logger.info("Toplam %s opportunity çekildi (sayfa: %s).", seen, page)

    # ---------- contacts ----------
    def search_contacts(self, limit: int = 100, page: int = 1) -> dict:
        body = {
            "locationId": self.config.location_id,
            "pageLimit": limit,
            "page": page,
        }
        return self._request("POST", "/contacts/search", json_body=body)

    # ---------- conversations ----------
    def search_conversations(
        self,
        contact_id: str | None = None,
        limit: int = 20,
        query: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "locationId": self.config.location_id,
            "limit": limit,
        }
        if contact_id:
            params["contactId"] = contact_id
        if query:
            params["query"] = query
        return self._request("GET", "/conversations/search", params=params)

    def get_conversation_messages(self, conversation_id: str, limit: int = 20) -> list[dict]:
        data = self._request(
            "GET",
            f"/conversations/{conversation_id}/messages",
            params={"limit": limit},
        )
        # Yanıt: {"messages": {"messages": [...], ...}}
        inner = (data.get("messages") or {})
        return inner.get("messages", []) or []

    def get_recent_messages_for_contact(
        self, contact_id: str, max_messages: int = 10
    ) -> list[dict]:
        """Contact'ın en son sohbetinin son N mesajını döner (kronolojik)."""
        convs = self.search_conversations(contact_id=contact_id, limit=1).get(
            "conversations", []
        )
        if not convs:
            return []
        msgs = self.get_conversation_messages(convs[0]["id"], limit=max_messages)
        return list(reversed(msgs))  # API genelde tersten döner

    # ---------- tasks ----------
    def search_tasks(self, contact_id: str | None = None) -> dict:
        if contact_id:
            return self._request("GET", f"/contacts/{contact_id}/tasks")
        # Bulk task search V2'de location bazlı endpoint sınırlı; contact bazlı ana yol.
        return {"tasks": []}

    # ---------- forms ----------
    def fetch_form_submissions(
        self,
        page: int = 1,
        page_limit: int = 100,
        start_at: int | None = None,
        end_at: int | None = None,
        form_id: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "locationId": self.config.location_id,
            "page": page,
            "pageLimit": page_limit,
        }
        if start_at is not None:
            params["startAt"] = start_at
        if end_at is not None:
            params["endAt"] = end_at
        if form_id:
            params["formId"] = form_id
        return self._request("GET", "/forms/submissions", params=params)

    def iter_all_form_submissions(
        self,
        date_after_ms: int | None = None,
        date_before_ms: int | None = None,
        max_records: int = 10000,
        page_limit: int = 100,
    ) -> Iterable[dict]:
        page = 1
        seen = 0
        while seen < max_records:
            batch_size = min(page_limit, max_records - seen)
            data = self.fetch_form_submissions(
                page=page,
                page_limit=batch_size,
                start_at=date_after_ms,
                end_at=date_before_ms,
            )
            batch = data.get("submissions", [])
            if not batch:
                break
            for s in batch:
                yield s
            seen += len(batch)
            total = data.get("total", 0)
            if seen >= total or len(batch) < batch_size:
                break
            page += 1
        logger.info("Toplam %s form submission çekildi.", seen)

    # ---------- convenience ----------
    def user_name_map(self) -> dict[str, str]:
        return {
            u["id"]: f"{u.get('firstName', '').strip()} {u.get('lastName', '').strip()}".strip()
            or u.get("email", "?")
            for u in self.list_users()
        }

    def custom_field_map(self) -> dict[str, dict]:
        return {f["id"]: f for f in self.list_custom_fields()}


if __name__ == "__main__":
    c = GHLClient()
    pls = c.list_pipelines()
    print(f"{len(pls)} pipeline.")
    for p in pls:
        print(f" - {p['name']}: {len(p.get('stages', []))} stage")
