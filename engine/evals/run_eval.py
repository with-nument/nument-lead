"""Golden-set evaluation: grades, facts and messages against labelled businesses (Step 17)."""

from __future__ import annotations

from typing import Any

from nument_engine.pipeline.runs import RunContext


def run(rc: RunContext, subset: int | None = None) -> dict[str, Any]:
    """Evaluate the engine on the golden set; `subset` limits it to N labels (fast CI check)."""
    raise NotImplementedError("Built in Step 17")
