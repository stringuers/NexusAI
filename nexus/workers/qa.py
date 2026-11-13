"""Platform-owned deterministic checks for the initial static-site template."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])


def check_site(root: Path) -> dict:
    checks = []
    index = root / "index.html"
    if not index.is_file() or index.is_symlink():
        return {"passed": False, "checks": [{"name": "index.html exists", "passed": False}]}
    if index.stat().st_size > 5 * 1024 * 1024:
        return {"passed": False, "checks": [{"name": "page size", "passed": False}]}
    page = Page()
    page.feed(index.read_text())
    for tag in ("title", "main", "h1", "nav"):
        checks.append({"name": f"{tag} landmark", "passed": any(t == tag for t, _ in page.tags)})
    checks.append(
        {
            "name": "document language",
            "passed": any(t == "html" and bool(a.get("lang")) for t, a in page.tags),
        }
    )
    checks.append(
        {
            "name": "responsive viewport",
            "passed": any(t == "meta" and a.get("name") == "viewport" for t, a in page.tags),
        }
    )
    checks.append(
        {
            "name": "image alternatives",
            "passed": all("alt" in a for t, a in page.tags if t == "img"),
        }
    )
    checks.append({"name": "navigation links", "passed": bool(page.links)})
    for link in page.links:
        parsed = urlsplit(link)
        valid = parsed.scheme in {"https", "http", "mailto", "tel"}
        if not parsed.scheme and not parsed.netloc:
            target = (root / unquote(parsed.path)).resolve() if parsed.path else index
            valid = target.is_relative_to(root.resolve()) and target.is_file()
            if parsed.fragment and not parsed.path:
                valid = valid and unquote(parsed.fragment) in page.ids
        checks.append({"name": f"link {link[:120]}", "passed": valid})
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "scope": "static HTML checks; no browser, build or unit-test claim",
    }
