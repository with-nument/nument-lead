"""AI router: task to provider and model, fallbacks, cache, cost log (Step 4).

Pipeline steps use only this package for AI:

    from nument_engine.llm import Router, AllProvidersDown, BudgetExceeded

    router = for_run(rc)                 # or Router.for_run(rc)
    try:
        judgement = router.run("judge_lead", inputs, lead_id=lead_id)    # LeadJudgement
    except BudgetExceeded as exc:         # the budget guard said no: record the skip, move on
        ...
    except AllProvidersDown as exc:       # every model in the chain failed: retry the item next run
        ...
    router.last_meta["tag"]               # "gemini:gemini-4-argon#judge_lead.v1": store it with the output

    res = router.run_result("check_message", inputs, exclude_model="gemini-3.8-flash")
    res.output, res.tag, res.model, res.fallback_from, res.inr   # output and metadata in one object

Batch work goes through `nument_engine.llm.batch` (submit at night, collect in the morning).
"""

from ..budget import Budget, BudgetExceeded, BudgetStop
from .config import ConfigError, ModelRef, TaskConfig, TaskRegistry, load_registry
from .router import AIResult, Router, TextOutput, for_run
from .types import AllProvidersDown, LLMError, OutputInvalid, ProviderError

__all__ = [
    "AIResult",
    "AllProvidersDown",
    "Budget",
    "BudgetExceeded",
    "BudgetStop",
    "ConfigError",
    "LLMError",
    "ModelRef",
    "OutputInvalid",
    "ProviderError",
    "Router",
    "TaskConfig",
    "TaskRegistry",
    "TextOutput",
    "for_run",
    "load_registry",
]
