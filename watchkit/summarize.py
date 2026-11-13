"""watchkit/summarize.py — Japanese 3-line summarizer interface.

The summarizer contract is simple:

    summarize(event: Event) -> str

The returned string always contains exactly three lines (separated by ``\\n``),
all in Japanese:
  - Line 1: what changed
  - Line 2: impact / scope
  - Line 3: recommended next action

Two implementations are provided:

* :class:`TemplateSummarizer` — deterministic, always works, no API key needed.
* :class:`LLMSummarizer` — calls an OpenAI-compatible chat endpoint when
  ``WATCHKIT_LLM_API_KEY`` is set; falls back to the template on any error.

:func:`get_summarizer` returns the appropriate instance based on environment.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Protocol

from watchkit.state import Event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol (interface)
# ---------------------------------------------------------------------------

class Summarizer(Protocol):
    """Interface for all summarizer implementations."""

    def summarize(self, event: Event) -> str:
        """Return exactly 3 newline-separated Japanese lines."""
        ...


# ---------------------------------------------------------------------------
# Template summarizer — deterministic, no external dependencies
# ---------------------------------------------------------------------------

# Maps event kind → (line1 template, line2 template, line3 template)
# {source}, {title}, {detail} are available as format variables.
_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "incident_opened": (
        "【障害発生】{source}で新たな障害が検出されました：{title}",
        "影響範囲：{source} のサービスが一部または全体的に影響を受けている可能性があります。",
        "公式ステータスページを確認し、業務への影響を評価してください。",
    ),
    "incident_updated": (
        "【障害更新】{source} の障害情報が更新されました：{title}",
        "影響範囲：引き続き {source} のサービスに影響が継続しています。",
        "公式ステータスページで最新情報を確認し、復旧の見通しを把握してください。",
    ),
    "incident_resolved": (
        "【障害復旧】{source} の障害が解決しました：{title}",
        "影響範囲：{source} のサービスは通常状態に戻っています。",
        "業務への影響がないことを確認し、必要に応じて関係者に周知してください。",
    ),
    "page_changed": (
        "【更新検知】{source} のページが変更されました：{title}",
        "変更内容：{detail_short}",
        "公式ページを確認し、試験日程・シラバス・受験料等の最新情報を把握してください。",
    ),
}

_DEFAULT_TEMPLATE: tuple[str, str, str] = (
    "【変更検知】{source} で変更が検出されました：{title}",
    "詳細：{detail_short}",
    "公式情報を確認し、必要な対応を検討してください。",
)


class TemplateSummarizer:
    """Deterministic Japanese summarizer using hard-coded templates."""

    def summarize(self, event: Event) -> str:
        """Build a 3-line Japanese summary from *event* using templates."""
        tmpl = _TEMPLATES.get(event.kind, _DEFAULT_TEMPLATE)
        detail_short = (event.detail[:80] + "…") if len(event.detail) > 80 else event.detail
        ctx = {
            "source": event.source,
            "title": event.title,
            "detail": event.detail,
            "detail_short": detail_short,
        }
        lines = [t.format(**ctx) for t in tmpl]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM summarizer — uses OpenAI-compatible chat API
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
以下のシステム変更イベントについて、日本語で3行のサマリーを作成してください。
1行目：何が変更されたか
2行目：影響範囲・スコープ
3行目：推奨される次のアクション

イベント種別: {kind}
ソース: {source}
タイトル: {title}
詳細: {detail}

必ず3行で回答してください。余計な説明は不要です。"""


class LLMSummarizer:
    """OpenAI-compatible chat summarizer with template fallback.

    Reads configuration from environment variables:
    - ``WATCHKIT_LLM_API_KEY`` (required)
    - ``WATCHKIT_LLM_BASE_URL`` (optional, default: https://api.openai.com/v1)
    - ``WATCHKIT_LLM_MODEL`` (optional, default: gpt-4o-mini)
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("WATCHKIT_LLM_API_KEY", "")
        self._base_url = os.environ.get(
            "WATCHKIT_LLM_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self._model = os.environ.get("WATCHKIT_LLM_MODEL", "gpt-4o-mini")
        self._fallback = TemplateSummarizer()

    def summarize(self, event: Event) -> str:
        """Call the LLM API; fall back to the template on any error."""
        try:
            return self._call_api(event)
        except Exception as exc:
            logger.warning(
                "LLM summarizer failed (%s); using template fallback.", exc
            )
            return self._fallback.summarize(event)

    def _call_api(self, event: Event) -> str:
        prompt = _LLM_PROMPT.format(
            kind=event.kind,
            source=event.source,
            title=event.title,
            detail=event.detail[:500],  # limit context size
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 300,
        }
        url = f"{self._base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        content: str = result["choices"][0]["message"]["content"].strip()
        # Ensure exactly 3 lines; pad or truncate if the model misbehaves
        lines = [l for l in content.splitlines() if l.strip()]
        if len(lines) >= 3:
            return "\n".join(lines[:3])
        # Pad with the template fallback lines if too short
        fallback_lines = self._fallback.summarize(event).splitlines()
        while len(lines) < 3:
            lines.append(fallback_lines[len(lines)])
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_summarizer() -> Summarizer:
    """Return the appropriate summarizer based on environment configuration.

    Returns :class:`LLMSummarizer` when ``WATCHKIT_LLM_API_KEY`` is set,
    otherwise :class:`TemplateSummarizer`.
    """
    if os.environ.get("WATCHKIT_LLM_API_KEY"):
        logger.info("LLM summarizer active (model: %s)",
                    os.environ.get("WATCHKIT_LLM_MODEL", "gpt-4o-mini"))
        return LLMSummarizer()
    logger.debug("Template summarizer active (no WATCHKIT_LLM_API_KEY set).")
    return TemplateSummarizer()
