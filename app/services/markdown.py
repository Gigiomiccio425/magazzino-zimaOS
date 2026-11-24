"""Markdown sicuro: HTML disattivato, link esterni con rel=noopener."""
from markdown_it import MarkdownIt
from markupsafe import Markup

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True})
_default_link_open = _md.renderer.rules.get("link_open")


def _link_open(renderer, tokens, idx, options, env):
    tokens[idx].attrSet("rel", "noopener noreferrer")
    tokens[idx].attrSet("target", "_blank")
    if _default_link_open:
        return _default_link_open(tokens, idx, options, env)
    return renderer.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _link_open)
_md.validateLink = lambda url: url.strip().lower().startswith(("http://", "https://", "/", "#", "mailto:"))


def render_markdown(text: str | None) -> Markup:
    return Markup(_md.render(text or ""))
