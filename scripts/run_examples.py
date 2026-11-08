"""Run the example queries in examples/requests.json against a running service and save each
request and its actual JSON response under examples/<name>/.

    uv run python scripts/run_examples.py [--service=http://localhost:8765]

The service writes its full working data to data/queries/<task_id>/ as usual; only the request
and the API response are kept here, so the examples show exactly what a client receives.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def http_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def run(service: str, request: dict) -> dict:
    task = http_json(f"{service}/queries", request)
    while True:
        status = http_json(f"{service}/queries/{task['task_id']}")
        if status["status"] in ("succeeded", "failed"):
            return status
        time.sleep(2)


def main() -> None:
    service = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--service=")), "http://localhost:8765")
    for example in json.loads((EXAMPLES / "requests.json").read_text()):
        status = run(service, example["request"])
        folder = EXAMPLES / example["name"]
        folder.mkdir(exist_ok=True)
        (folder / "request.json").write_text(json.dumps(example["request"], indent=2) + "\n")
        body = status["result"] if status["status"] == "succeeded" else status["error"]
        (folder / "response.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        viz = (status.get("result") or {}).get("visualization") or {}
        print(f"{example['name']:24} {status['status']:9} {viz.get('type', '-'):16} {viz.get('title', status.get('error'))}")


if __name__ == "__main__":
    main()
