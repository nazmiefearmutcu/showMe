"""Awareness Markets bridge — showme's source for news, sentiment and calendars.

Awareness (sibling project, ``awareness-markets`` service on 127.0.0.1:8086) owns
every text/event/sentiment data responsibility: quality-gated sourced news
clustered into stories, FinBERT sentiment, economic and corporate calendars,
holidays, SEC filings and market-sentiment indicators. showme only reads it.
"""

from showme.engine.data_sources.awareness.client import (
    AwarenessClient,
    AwarenessResponse,
    AwarenessUnavailable,
    awareness_base_url,
    get_awareness_client,
)

__all__ = [
    "AwarenessClient",
    "AwarenessResponse",
    "AwarenessUnavailable",
    "awareness_base_url",
    "get_awareness_client",
]
