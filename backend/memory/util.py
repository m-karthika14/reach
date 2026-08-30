"""URL -> (domain, page) helpers for memory keys."""

from urllib.parse import urlparse


def domain_of(url: str) -> str:
    try:
        p = urlparse(url or "")
    except ValueError:
        return "unknown"
    if p.netloc:
        return p.netloc.lower()
    # file:// URLs (the demo site) -> use the containing folder name
    parts = [seg for seg in p.path.replace("\\", "/").split("/") if seg]
    if len(parts) >= 2:
        return parts[-2].lower()
    return "local"


def page_of(url: str) -> str:
    try:
        p = urlparse(url or "")
    except ValueError:
        return "index"
    parts = [seg for seg in p.path.replace("\\", "/").split("/") if seg]
    last = parts[-1] if parts else "index"
    return last.split("?")[0] or "index"
