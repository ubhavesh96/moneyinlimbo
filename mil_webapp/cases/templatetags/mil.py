"""Template filters for the officer console and auditor views."""

from __future__ import annotations

import difflib
import json
import re
from datetime import date, datetime

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

RAILS = {"UPI": "UPI", "UPI_MERCHANT": "UPI merchant", "IMPS": "IMPS", "CARD_TO_CARD": "Card to card",
         "CARD_POS": "Card PoS", "CARD_ONLINE": "Card online", "ATM": "ATM", "UNKNOWN": "Unknown"}
STATUS = {"New": "new", "Agent working": "working", "Needs your review": "review", "Awaiting customer": "waiting",
          "Escalated": "escalated", "Resolved": "resolved", "Overdue": "overdue", "Closed": "closed"}


def _indian(n: float) -> str:
    whole, frac = f"{abs(n):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    out = ",".join(([head] if head else []) + groups + [tail])
    return ("-" if n < 0 else "") + (out if frac == "00" else f"{out}.{frac}")


@register.filter
def inr(value) -> str:
    """4250 -> '₹4,250'; 125000 -> '₹1,25,000'."""
    if value in (None, ""):
        return "—"
    try:
        return "₹" + _indian(float(value))
    except (TypeError, ValueError):
        return str(value)


@register.filter
def rail(value) -> str:
    return RAILS.get(value or "", value or "—")


@register.filter
def status_slug(value) -> str:
    return STATUS.get(value or "", "closed")


@register.filter
def nicedate(value) -> str:
    if not value:
        return "—"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(value)


@register.filter
def nicetime(value) -> str:
    """ISO timestamp (UTC) -> '17 Oct 2026, 11:42 IST'."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    from zoneinfo import ZoneInfo

    try:
        dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        return dt.strftime("%d %b %Y, %H:%M IST")
    except Exception:  # tzdata missing on some Windows installs
        return dt.strftime("%d %b %Y, %H:%M UTC")


@register.filter
def pct(value) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


@register.filter
def conf_level(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "low"
    return "high" if v >= 0.85 else "medium" if v >= 0.6 else "low"


@register.filter
def prettyjson(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def humanize(value) -> str:
    return str(value or "").replace("_", " ")


@register.filter
def cited(text) -> str:
    """Escape a draft and turn [n] markers into footnote links; keep line breaks."""
    html = escape(text or "")
    html = re.sub(r"\[(\d+)\]", r'<a class="fn" href="#cite-\1" aria-label="Source \1">[\1]</a>', html)
    return mark_safe(html.replace("\n", "<br>"))


@register.simple_tag
def asset(path: str) -> str:
    """Static URL with a content fingerprint (?v=...), so browsers never keep a stale CSS/JS file."""
    import hashlib

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    with open(found, "rb") as fh:
        digest = hashlib.sha1(fh.read()).hexdigest()[:10]
    return f"{url}?v={digest}"


@register.simple_tag
def worddiff(before: str, after: str):
    """Word-level diff of the AI draft against the final text: <del> removed, <ins> added."""
    a, b = re.split(r"(\s+)", before or ""), re.split(r"(\s+)", after or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape("".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            out.append(f"<del>{escape(''.join(a[i1:i2]))}</del>")
        if op in ("insert", "replace"):
            out.append(f"<ins>{escape(''.join(b[j1:j2]))}</ins>")
    return mark_safe("".join(out).replace("\n", "<br>"))
