"""Regex-based redaction applied to the LLM digest.

The store keeps raw transcripts intact (that's a deliberate design choice — you
might want to grep them later). Redaction runs only on the *digest text* that's
about to be POSTed to a third-party LLM provider. Default patterns target
high-confidence credentials and PII; users can extend via `HINDSIGHT_REDACT_FILE`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Pattern


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: Pattern[str]
    placeholder: str


# Order matters: longer / more specific patterns first so they win against
# generic fallbacks. Each redaction is replaced with a stable placeholder so
# the LLM still sees that *something* was there (and can reason about it).
DEFAULT_RULES: tuple[Rule, ...] = (
    # Cloud / AI provider keys (high-confidence)
    Rule("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<ANTHROPIC_KEY>"),
    Rule("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "<OPENAI_KEY>"),
    Rule("ark_key", re.compile(r"ark-[a-f0-9-]{30,}"), "<ARK_KEY>"),
    Rule("gh_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "<GITHUB_TOKEN>"),
    Rule("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<AWS_ACCESS_KEY>"),
    Rule("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "<SLACK_TOKEN>"),
    Rule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "<GOOGLE_API_KEY>"),
    # Generic high-entropy bearer / JWT
    Rule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_=]{8,}\.[A-Za-z0-9_=]{8,}\.[A-Za-z0-9_=\-+/]{8,}\b"),
        "<JWT>",
    ),
    Rule(
        "bearer_header",
        re.compile(r"(?i)\bauthorization:\s*bearer\s+[A-Za-z0-9._\-+/=]{12,}"),
        "Authorization: Bearer <REDACTED>",
    ),
    # Network / PII
    Rule(
        "private_ipv4",
        re.compile(
            r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[0-1]))(?:\.\d{1,3}){2,3}\b"
        ),
        "<PRIVATE_IP>",
    ),
    Rule(
        "email",
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        "<EMAIL>",
    ),
    # ssh url with embedded password (sshpass / ssh -p style we saw earlier)
    Rule(
        "sshpass",
        re.compile(r"sshpass\s+-p\s+\S+"),
        "sshpass -p <REDACTED>",
    ),
)


def load_user_rules(path: Path | None) -> tuple[Rule, ...]:
    """Load extra rules from a tiny TSV file. Format:

        name<TAB>regex<TAB>placeholder

    Lines starting with '#' or blank lines are ignored. Invalid regex lines are
    skipped silently rather than crashing the digest path.
    """
    if not path or not path.exists():
        return ()
    out: list[Rule] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, pattern, placeholder = parts
        try:
            out.append(Rule(name, re.compile(pattern), placeholder))
        except re.error:
            continue
    return tuple(out)


def redact(text: str, rules: Iterable[Rule] = DEFAULT_RULES) -> tuple[str, dict[str, int]]:
    """Apply rules in order. Returns (redacted_text, hit_counts_by_rule)."""
    counts: dict[str, int] = {}
    for r in rules:
        new, n = r.pattern.subn(r.placeholder, text)
        if n:
            counts[r.name] = counts.get(r.name, 0) + n
            text = new
    return text, counts


def build_rules(user_rules_path: Path | None = None) -> tuple[Rule, ...]:
    """Default rules + user rules. User rules go *first* so they can pre-empt defaults."""
    user = load_user_rules(user_rules_path)
    return user + DEFAULT_RULES


def rules_from_env() -> tuple[Rule, ...]:
    """Convenience: read HINDSIGHT_REDACT_FILE if set, fall back to defaults."""
    env = os.getenv("HINDSIGHT_REDACT_FILE")
    return build_rules(Path(os.path.expanduser(env)) if env else None)
