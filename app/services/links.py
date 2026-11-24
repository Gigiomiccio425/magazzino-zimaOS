"""Link (es. GitHub): tipo, repo e numero ricavati solo leggendo l'URL. Nessuna chiamata di rete."""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..models import Link

KIND_LABELS = {"github_commit": "Commit", "github_pr": "Pull request", "github_issue": "Issue",
               "github_release": "Release", "github_repo": "Repo", "altro": "Link"}
_PATTERNS = [
    (re.compile(r"^/([^/]+)/([^/]+)/commit/([0-9a-fA-F]{4,40})"), "github_commit"),
    (re.compile(r"^/([^/]+)/([^/]+)/pull/(\d+)"), "github_pr"),
    (re.compile(r"^/([^/]+)/([^/]+)/issues/(\d+)"), "github_issue"),
    (re.compile(r"^/([^/]+)/([^/]+)/releases/tag/([^/]+)"), "github_release"),
]


@dataclass(frozen=True)
class LinkInfo:
    kind: str
    owner: str
    repo: str
    ref: str


def is_safe_url(url: str) -> bool:
    u = urlparse((url or "").strip())
    return u.scheme in ("http", "https") and bool(u.netloc)


def parse_link(url: str) -> LinkInfo:
    u = urlparse((url or "").strip())
    if u.netloc.lower() not in ("github.com", "www.github.com"):
        return LinkInfo("altro", "", "", "")
    for pattern, kind in _PATTERNS:
        m = pattern.match(u.path)
        if m:
            return LinkInfo(kind, m.group(1), m.group(2), m.group(3))
    m = re.match(r"^/([^/]+)/([^/]+?)(?:\.git)?/?$", u.path)
    if m:
        return LinkInfo("github_repo", m.group(1), m.group(2), "")
    return LinkInfo("altro", "", "", "")


def links_from_form(form) -> tuple[list[tuple[str, str]], str | None]:
    """Coppie (url, titolo) dal form; errore se un URL non e' http(s)."""
    out = []
    for url, title in zip(form.getlist("link_url"), form.getlist("link_title")):
        url, title = (url or "").strip(), (title or "").strip()
        if not url:
            continue
        if not is_safe_url(url):
            return [], f"Link non valido: {url[:60]}"
        out.append((url[:1000], title[:200]))
    return out, None


def save_links(db: Session, entity_type: str, entity_id: int, pairs: list[tuple[str, str]]) -> list[Link]:
    links = []
    for url, title in pairs:
        info = parse_link(url)
        link = Link(entity_type=entity_type, entity_id=entity_id, url=url, title=title, kind=info.kind,
                    owner=info.owner, repo=info.repo, ref=info.ref)
        db.add(link)
        links.append(link)
    db.flush()
    return links


def links_for(db: Session, entity_type: str, entity_ids) -> dict[int, list[Link]]:
    ids = list(entity_ids)
    out: dict[int, list[Link]] = {i: [] for i in ids}
    if ids:
        for link in db.query(Link).filter(Link.entity_type == entity_type, Link.entity_id.in_(ids)).order_by(Link.id):
            out[link.entity_id].append(link)
    return out
