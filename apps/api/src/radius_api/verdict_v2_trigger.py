"""Ask the worker to refresh verdict v2 after a human intent decision (DEC-033).

The API holds no GitHub credentials and does no scoring. After an authenticated,
correctly scoped criterion change it upserts one row into the ``verdict_v2_requests``
outbox (keyed by analysis, so several quick changes collapse into one). The worker
reads the criterion states from the database, refreshes the stored Stage A bundle,
re-scores Stage B and republishes. Nothing here carries provenance: only the stored
criterion state decides what counts as ``human_confirmed``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from radius_shared.logging import get_logger
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_repository import VerdictV2Repository

LOGGER = get_logger("radius.api.verdict_v2")

#: Trailing debounce: each change pushes the recompute this far into the future, so
#: a burst of confirms is scored once.
INTENT_DEBOUNCE_SECONDS = 3.0
INTENT_REASON = "intent_changed"


def request_verdict_v2_recompute(
    request: Request,
    verdicts: VerdictV2Repository,
    organization_id: UUID,
    analysis_id: UUID,
) -> bool:
    """Enqueue a debounced recompute; True when a request was written.

    No-op with the flag off. Never raises: a failure must not undo or fail the
    criterion change, so it is logged and the stored verdict stays as it was.
    """

    mode = getattr(request.app.state.settings, "verdict_v2_mode", VerdictV2Mode.OFF)
    if mode == VerdictV2Mode.OFF:
        return False
    try:
        verdicts.enqueue_request(
            organization_id,
            analysis_id,
            INTENT_REASON,
            delay_seconds=INTENT_DEBOUNCE_SECONDS,
        )
    except Exception as exc:
        LOGGER.warning(
            "Could not enqueue verdict v2 recompute: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(analysis_id)},
        )
        return False
    return True
