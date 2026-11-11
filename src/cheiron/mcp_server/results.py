"""Finished answers on disk, shared by every cheiron-mcp process and the local web page.

    $CHEIRON_HOME/results/<result_id>.json     {"result_id", "created_at", "request", "response"}

CHEIRON_HOME defaults to ~/.cheiron. Results are plain files, so a link to one keeps working after
the Claude session that made it has ended (open it with `cheiron-mcp serve`).
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cheiron.models.request import QueryRequest
from cheiron.models.response import QueryResponse

RESULT_ID = re.compile(r"^[a-z0-9-]{8,64}$")


def cheiron_home() -> Path:
    return Path(os.environ.get("CHEIRON_HOME") or Path.home() / ".cheiron")


class ResultStore:
    def __init__(self, root: Path | None = None):
        self.root = root or cheiron_home() / "results"

    def save(self, request: QueryRequest, response: QueryResponse) -> str:
        """Write one answer; return its id (date first, so ids sort by time)."""
        self.root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        result_id = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        document = {
            "result_id": result_id,
            "created_at": now.isoformat(),
            "request": request.model_dump(mode="json", exclude_none=True),
            "response": response.model_dump(mode="json", by_alias=True),
        }
        path = self.root / f"{result_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document, ensure_ascii=False))
        tmp.replace(path)  # readers never see a half-written file
        return result_id

    def load(self, result_id: str) -> dict[str, Any] | None:
        if not RESULT_ID.match(result_id):
            return None
        path = self.root / f"{result_id}.json"
        return json.loads(path.read_text()) if path.is_file() else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest first: id, time, question and chart title (not the data)."""
        if not self.root.is_dir():
            return []
        items = []
        for path in sorted(self.root.glob("*.json"), reverse=True)[:limit]:
            try:
                doc = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            items.append(
                {
                    "result_id": doc["result_id"],
                    "created_at": doc["created_at"],
                    "query": doc["request"].get("query"),
                    "title": doc["response"]["visualization"].get("title"),
                }
            )
        return items
