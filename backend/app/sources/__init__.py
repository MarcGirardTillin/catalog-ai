"""Pluggable source fetchers: where brand data/images come from.

Implemented: shopify_json (suggest.json search + products/{handle}.json).
Planned: firecrawl fallback (full-page extraction), Bright Data unlocker
(Phase 3) — the resolver's `method` parameter is the extension point.
"""
