"""Download the web page's JavaScript into src/studytrials/web/vendor/, pinned, so the page works offline
and can be inlined into the MCP App resource (a sandboxed iframe that may not load CDN scripts).

    uv run python scripts/vendor_web_assets.py

The MCP Apps SDK ships as an ES module; it is rewritten into a classic script that sets
`window.McpApps`, so the page can use it from an inline <script> without imports.
"""

import re
import sys
from pathlib import Path

import httpx

VENDOR = Path(__file__).resolve().parents[1] / "src" / "studytrials" / "web" / "vendor"
CDN = "https://cdn.jsdelivr.net/npm"
ASSETS = {
    "vega.min.js": f"{CDN}/vega@5.30.0/build/vega.min.js",
    "vega-lite.min.js": f"{CDN}/vega-lite@5.21.0/build/vega-lite.min.js",
    "vega-embed.min.js": f"{CDN}/vega-embed@6.26.0/build/vega-embed.min.js",
    "mcp-apps.js": f"{CDN}/@modelcontextprotocol/ext-apps@2.0.4/dist/src/app-with-deps.js",
}


def module_to_global(source: str, name: str) -> str:
    """Turn a bundled ES module whose only export statement is its last `export{a as B,...}` into
    a classic script that assigns those exports to window[name]."""
    match = re.search(r"export\s*\{([^}]*)\}\s*;?\s*$", source)
    if not match or re.search(r"^\s*import[\s{*]", source, re.M) or "import.meta" in source:
        raise SystemExit(f"{name}: not a self-contained bundle with one trailing export; check the package")
    pairs = [p.strip().split(" as ") for p in match.group(1).split(",") if p.strip()]
    exports = ",".join(f"{alias}:{local}" for local, alias in ((p[0], p[-1]) for p in pairs))
    return f"(()=>{{{source[: match.start()]}\nwindow.{name}={{{exports}}};}})();\n"


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for filename, url in ASSETS.items():
            response = client.get(url)
            response.raise_for_status()
            text = response.text
            if filename == "mcp-apps.js":
                text = module_to_global(text, "McpApps")
            (VENDOR / filename).write_text(text)
            print(f"{filename}: {len(text) / 1024:.0f} KB from {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
