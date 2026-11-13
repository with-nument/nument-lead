"""`nlead health --models` and `nlead health --llm-smoke` (Step 4.4.3 and 4.12).

--models     lists the models each usable provider offers to our keys and checks every model in tasks.yaml:
             a missing Gemini model FAILS (Gemini must always work); OpenAI problems are warnings only.
--llm-smoke  sends one tiny request per task on every usable model of each chain and prints a table with
             tokens and cost. It runs under a built-in --max-spend-inr of 5 and records costs like any run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..budget import BudgetExceeded
from ..logging import get_logger
from .config import ModelRef, TaskRegistry, load_registry
from .router import Router
from .types import AllProvidersDown, LLMError

log = get_logger("nlead.llm")

SMOKE_MAX_SPEND_INR = 5.0
Out = Callable[[str], None]


@dataclass
class ModelCheck:
    level: str  # OK, WARN, FAIL
    line: str


@dataclass
class SmokeRow:
    task: str
    provider: str
    model: str
    role: str  # primary, fallback
    ok: bool | None  # None: skipped
    detail: str
    input_tokens: int = 0
    output_tokens: int = 0
    inr: float = 0.0


@dataclass
class SmokeReport:
    rows: list[SmokeRow] = field(default_factory=list)

    @property
    def total_inr(self) -> float:
        return sum(r.inr for r in self.rows)

    @property
    def failures(self) -> int:
        return sum(1 for r in self.rows if r.ok is False)


def check_models(registry: TaskRegistry, router: Router, *, tiers: tuple[str, ...] = ()) -> list[ModelCheck]:
    """Compare configured model ids with what each provider lists for our keys."""
    checks: list[ModelCheck] = []
    available: dict[str, dict[str, list[str]] | None] = {}
    for provider in ("gemini", "openai"):
        reason = router.availability.provider_reason(provider)
        if reason is None and provider not in router.providers:
            reason = f"no {provider} API key"
        if reason:
            level = "FAIL" if provider == "gemini" else "WARN"
            checks.append(ModelCheck(level, f"{level:4}  {provider}: skipped ({reason})"))
            available[provider] = None
            continue
        try:
            models = router.providers[provider].list_models()
        except LLMError as exc:
            level = "FAIL" if provider == "gemini" else "WARN"
            checks.append(ModelCheck(level, f"{level:4}  {provider}: cannot list models ({exc})"))
            available[provider] = None
            continue
        available[provider] = {m.name: m.actions for m in models}
        checks.append(ModelCheck("OK", f"OK    {provider}: {len(models)} models listed for this key"))

    registries = [registry] + [load_registry(t) for t in tiers if t != registry.tier]
    seen: set[tuple[str, ModelRef]] = set()
    for reg in registries:
        active = reg.tier == registry.tier
        for name, cfg in sorted(reg.tasks.items()):
            refs = [*cfg.chain, *([cfg.structure_with] if cfg.structure_with else [])]
            for index, ref in enumerate(refs):
                if (name, ref) in seen:
                    continue
                seen.add((name, ref))
                role = "primary" if index == 0 else "fallback"
                listing = available.get(ref.provider)
                where = f"{name} {role} {ref}" + ("" if active else f" (tier {reg.tier})")
                if listing is None:
                    usable = next((r for r in cfg.chain if available.get(r.provider)), None)
                    hint = f". Will use {usable}" if usable else ""
                    checks.append(ModelCheck("WARN", f"WARN  {where} skipped{hint}"))
                    continue
                if ref.model not in listing:
                    close = sorted(m for m in listing if m.startswith(ref.model.split("-")[0] + "-"))
                    near = [m for m in close if ref.model.rsplit("-", 1)[0] in m][:3]
                    level = "FAIL" if ref.provider == "gemini" and active else "WARN"
                    checks.append(
                        ModelCheck(level, f"{level:4}  {where} not found. Closest: {', '.join(near) or 'none'}")
                    )
                    continue
                actions = listing[ref.model]
                spec = reg.spec(ref)
                if ref.provider == "gemini" and actions and "generateContent" not in actions:
                    checks.append(ModelCheck("FAIL", f"FAIL  {where} does not support generateContent"))
                elif cfg.mode == "batch" and spec.batch and actions and "batchGenerateContent" not in actions:
                    checks.append(ModelCheck("WARN", f"WARN  {where} has no batch API on this key"))
                else:
                    checks.append(ModelCheck("OK", f"OK    {where}"))
    return checks


# Tiny fixed inputs for every task. They follow the prompt contracts in engine/prompts/README.md.
SMOKE_INPUTS: dict[str, dict[str, Any]] = {
    "classify_signal": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "source": "apna",
        "url": "https://example.com/jobs/1",
        "title": "Front Desk Receptionist",
        "text": "Sunrise Dental Clinic, Baner, Pune is hiring a front desk receptionist to answer patient calls "
        "and WhatsApp enquiries and book appointments. Apply by 30 November.",
    },
    "classify_news": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "url": "https://example.com/news/1",
        "title": "Sunrise Dental opens second clinic in Pune",
        "text": "Sunrise Dental Clinic has opened its second branch in Kothrud, Pune, adding six dental chairs, "
        "said founder Dr. Asha Mehta on Monday.",
    },
    "classify_page_change": {
        "business_name": "Sunrise Dental Clinic",
        "url": "https://example.com/careers",
        "old_text": "Careers. No openings right now.",
        "new_text": "Careers. We are hiring: Patient Coordinator (Baner). Send your CV to jobs@example.com.",
    },
    "extract_facts": {
        "business_name": "Sunrise Dental Clinic",
        "segment_id": "clinics-in",
        "country": "in",
        "website": "https://example.com",
        "pages": [
            {
                "url": "https://example.com/",
                "text": "Sunrise Dental Clinic. Two branches in Baner and Kothrud, Pune. Call reception on "
                "+91 98200 00000 or WhatsApp us to book. Founded by Dr. Asha Mehta, Chief Dentist.",
            },
            {
                "url": "https://example.com/careers",
                "text": "We are hiring a Patient Coordinator for our Baner clinic.",
            },
        ],
    },
    "verify_flagged": {
        "business_name": "Sunrise Dental Clinic",
        "field": "branches",
        "question": "These facts about branches disagree. Which one does the page text support?",
        "facts": [
            {
                "id": "F1",
                "field": "branches",
                "value": {"count": 2},
                "quote": "Two branches in Baner and Kothrud",
                "url": "https://example.com/",
            },
            {
                "id": "F2",
                "field": "branches",
                "value": {"count": 1},
                "quote": "our clinic in Baner",
                "url": "https://example.com/about",
            },
        ],
        "pages": [{"url": "https://example.com/", "text": "Sunrise Dental Clinic. Two branches in Baner and Kothrud."}],
    },
    "judge_lead": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "city": "Pune",
        "business_name": "Sunrise Dental Clinic",
        "packaged_outcome_name": "AI front desk",
        "pitch_mode": "visible_pain",
        "total": 64.0,
        "fit": 3,
        "can_pay": 2.0,
        "intent": 8.0,
        "reach": 1.0,
        "grade": "B",
        "reasons": {"fit": "dental clinic with 2 branches", "intent": "hiring a patient coordinator 5 days ago"},
        "facts": [
            {
                "id": "F1",
                "field": "branches",
                "value": {"count": 2},
                "quote": "Two branches in Baner and Kothrud",
                "url": "https://example.com/",
            },
            {
                "id": "F2",
                "field": "decision_maker",
                "value": {"name": "Dr. Asha Mehta", "role": "Chief Dentist"},
                "quote": "Founded by Dr. Asha Mehta, Chief Dentist",
                "url": "https://example.com/",
            },
        ],
        "signals": [
            {
                "id": "S1",
                "type": "hiring_frontdesk",
                "category": "visible_pain",
                "age_days": 5,
                "quote": "We are hiring a Patient Coordinator for our Baner clinic.",
                "url": "https://example.com/careers",
                "details": {},
            },
        ],
        "allowed_angles": ["missed_calls", "hire_complement", "after_hours"],
        "contacts_summary": ["mobile (website)"],
    },
    "write_message": {
        "segment_id": "clinics-in",
        "domain": "clinics",
        "country": "in",
        "country_name": "India",
        "city": "Pune",
        "pitch_mode": "visible_pain",
        "angle": "hire_complement",
        "angle_idea": "we ship the first version now, their new hire runs it",
        "packaged_outcome_name": "AI front desk",
        "packaged_outcome": "every enquiry answered within seconds, followed up until it books",
        "business_name": "Sunrise Dental",
        "person_name": "Dr. Asha Mehta",
        "person_role": "Chief Dentist",
        "greeting": "Hi Dr. Mehta,",
        "seen_where": "your careers page",
        "what_we_saw": "hiring a patient coordinator for the Baner clinic",
        "facts": [{"id": "F1", "field": "branches", "value": {"count": 2}}],
        "signals": [{"id": "S1", "type": "hiring_frontdesk", "summary": "hiring a patient coordinator in Baner"}],
        "associate_name": "Aditya",
        "needs_email": False,
        "feedback": [],
        "avoid_openers": [],
        "avoid_questions": [],
    },
    "check_message": {
        "message": "Hi Dr. Mehta, saw on your careers page that you're hiring a patient coordinator for Baner. "
        "We're Nument, a small dev team. We could set up an AI front desk that answers WhatsApp enquiries "
        "in seconds and books slots, so your new hire starts with less load. Worth a look?",
        "greeting": "Hi Dr. Mehta,",
        "pitch_mode": "visible_pain",
        "facts": [{"id": "F1", "field": "branches", "value": {"count": 2}}],
        "signals": [{"id": "S1", "type": "hiring_frontdesk", "summary": "hiring a patient coordinator in Baner"}],
    },
    "classify_feed_job": {
        "feed": "hn",
        "url": "https://news.ycombinator.com/item?id=1",
        "text": "Brightcart | Full-stack engineer (contract) | Austin, TX | REMOTE (US) | https://brightcart.example\n"
        "We are a 9-person team building ordering software for independent grocers and need help shipping our "
        "React Native app.",
    },
    "find_decision_maker": {
        "name": "Brightcart Foods",
        "city": "Pune",
        "country": "India",
        "website": "https://brightcart.in",
    },
    "find_website": {
        "name": "Brightcart Foods",
        "city": "Pune",
        "country": "India",
        "need": "Hiring a React Native developer for their ordering app",
    },
    "lookup_reviews": {
        "name": "Sunrise Dental Clinic",
        "city": "Pune",
        "country": "India",
        "kind": "clinic",
        "website": "https://sunrisedental.example",
        "practo": True,
        "roles": ["receptionist", "front desk", "patient coordinator"],
    },
    "classify_reviews": {
        "business_name": "Sunrise Dental Clinic",
        "source": "Google Maps reviews",
        "reviews": [
            {"n": 1, "age": "3 weeks ago", "rating": 2.0, "text": "Called five times to book, nobody picked up."},
            {"n": 2, "age": "2 months ago", "rating": 5.0, "text": "Painless root canal, very kind doctor."},
        ],
    },
    "grounded_search": {
        "domain": "clinics",
        "country": "India",
        "days": 30,
        "queries": ["clinic looking for WhatsApp chatbot developer India"],
    },
    "weekly_audit": {
        "business_name": "Sunrise Dental Clinic",
        "segment_id": "clinics-in",
        "grade": "B",
        "pitch_mode": "visible_pain",
        "message": "Hi Dr. Mehta, saw you're hiring a patient coordinator for Baner. We're Nument, a small dev "
        "team. An AI front desk could answer WhatsApp enquiries in seconds. Worth a look?",
        "facts": [
            {"id": "F1", "field": "branches", "value": {"count": 2}, "quote": "Two branches in Baner and Kothrud"}
        ],
        "pages": [
            {
                "url": "https://example.com/",
                "text": "Sunrise Dental Clinic. Two branches in Baner and Kothrud, "
                "Pune. Call reception on +91 98200 00000.",
            }
        ],
    },
}


def llm_smoke(router: Router, *, primaries_only: bool = False, tasks: list[str] | None = None) -> SmokeReport:
    """One tiny request per task on every usable model of its chain (primaries first)."""
    report = SmokeReport()
    names = tasks or sorted(router.registry.tasks)
    plan: list[tuple[int, str, ModelRef]] = []
    for name in names:
        cfg = router.registry.task(name)
        for index, ref in enumerate(cfg.chain):
            if primaries_only and index > 0:
                break
            plan.append((index, name, ref))
    plan.sort(key=lambda item: item[0])  # every task on its primary before any fallback
    for index, name, ref in plan:
        role = "primary" if index == 0 else "fallback"
        reason = router.skip_reason(ref)
        if reason:
            report.rows.append(SmokeRow(name, ref.provider, ref.model, role, None, f"skip ({reason})"))
            continue
        try:
            res = router.run_result(name, SMOKE_INPUTS[name], models=[ref], use_cache=False)
        except BudgetExceeded as exc:
            report.rows.append(SmokeRow(name, ref.provider, ref.model, role, None, f"skip (budget: {exc.reason})"))
            continue
        except AllProvidersDown as exc:
            report.rows.append(SmokeRow(name, ref.provider, ref.model, role, False, f"failed: {exc}"[:200]))
            continue
        detail = "ok"
        if res.grounding:
            detail = f"ok q={len(res.grounding.get('queries', []))} sources={len(res.grounding.get('sources', []))}"
        row = SmokeRow(name, ref.provider, ref.model, role, True, detail)
        row.input_tokens, row.output_tokens, row.inr = res.usage.input_tokens, res.usage.output_tokens, res.inr
        report.rows.append(row)
    return report


def format_smoke(report: SmokeReport) -> list[str]:
    lines = [f"{'task':22} {'provider':8} {'model':24} {'role':8} {'result':28} {'in/out tokens':>14} {'cost':>8}"]
    for r in report.rows:
        tokens = f"{r.input_tokens}/{r.output_tokens}" if r.ok else ""
        cost = f"₹{r.inr:.3f}" if r.ok else ""
        lines.append(f"{r.task:22} {r.provider:8} {r.model:24} {r.role:8} {r.detail[:28]:28} {tokens:>14} {cost:>8}")
    lines.append(f"{'total':95} ₹{report.total_inr:.3f}")
    return lines


def run(rc: Any, *, models: bool, smoke: bool, providers: str | None = None, out: Out = print) -> int:
    """Entry point for the CLI. Returns the number of failures (the CLI exits non-zero when it is > 0)."""
    override = None
    if providers:
        wanted = {p.strip() for p in providers.split(",") if p.strip()}
        override = {p: p in wanted for p in ("gemini", "openai")}
    max_spend = rc.opts.max_spend_inr if rc.opts.max_spend_inr is not None else SMOKE_MAX_SPEND_INR
    router = Router(run_id=rc.run_id, max_spend_inr=max_spend, stats=rc.stats, enabled_override=override)
    failures = 0
    if models:
        checks = check_models(router.registry, router, tiers=("balanced", "best", "lean"))
        for check in checks:
            out(check.line)
        failures += sum(1 for c in checks if c.level == "FAIL")
        rc.stats["model_check_failures"] = failures
    if smoke:
        report = llm_smoke(router)
        for line in format_smoke(report):
            out(line)
        failures += report.failures
        rc.stats["llm_smoke"] = {"total_inr": round(report.total_inr, 4), "failures": report.failures}
    return failures
