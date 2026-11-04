"""Reader selection: explicit per-task provider routing (Phase 3).

`get_reader` delegates to the provider registry: exactly one reader is
selected from configuration (fixture in dev/test/demo, Spark / Spark
Open / Glimmer otherwise). There is no fallback chain — an
unconfigured or unavailable selection fails closed with an explicit
error. Kept as the pipeline's stable seam so call sites stay unchanged.
"""

from __future__ import annotations

from app.adapters.readers import Reader
from app.config import Settings
from app.providers.registry import resolve_reader


def get_reader(settings: Settings) -> Reader:
    return resolve_reader(settings)
