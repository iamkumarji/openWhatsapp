"""Jira Cloud REST client (read-only mirror). Basic auth: email + API token.

Sync (app.workers.tasks.sync_jira) UPSERTs into jira_issues/jira_projects and tracks
an updated-since cursor in sync_state so each run only pulls deltas.
"""
from __future__ import annotations

import base64

import httpx

from app.core.config import settings


class JiraClient:
    def __init__(self):
        self.base = settings.jira_base_url.rstrip("/")
        token = base64.b64encode(
            f"{settings.jira_email}:{settings.jira_api_token}".encode()
        ).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}

    async def search(self, jql: str, start_at: int = 0, max_results: int = 50) -> dict:
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": "summary,status,priority,issuetype,assignee,duedate,updated,project,sprint",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self.base}/rest/api/3/search", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def issues_updated_since(self, account_id: str, since_iso: str | None) -> list[dict]:
        jql = f'assignee = "{account_id}"'
        if since_iso:
            jql += f' AND updated >= "{since_iso}"'
        jql += " ORDER BY updated ASC"
        out, start = [], 0
        while True:
            page = await self.search(jql, start_at=start)
            out.extend(page.get("issues", []))
            start += len(page.get("issues", []))
            if start >= page.get("total", 0) or not page.get("issues"):
                break
        return out


jira_client = JiraClient()
