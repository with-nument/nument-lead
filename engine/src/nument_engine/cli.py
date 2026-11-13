"""`nlead` command line (A.12.6).

Global flags work on every command, before or after it:
    nlead --env dev --segment clinics-in --limit 20 --dry-run universe
    nlead universe --segment clinics-in --limit 20 --dry-run --env dev
Every pipeline command runs inside a run context, so the `runs` row, the logs and the costs share one run id.
Imports happen inside each command, which keeps `nlead --help` fast and lets unbuilt stages exist as stubs.
"""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from .pipeline.runs import Options, RunContext

SEGMENT_ID = re.compile(r"^[a-z0-9]+-[a-z]{2}$")
GLOBAL_VALUE_OPTIONS = frozenset({"--env", "--segment", "--limit", "--max-spend-inr"})
GLOBAL_FLAG_OPTIONS = frozenset({"--dry-run", "--json-logs", "--pretty-logs"})


def hoist_global_options(args: list[str]) -> list[str]:
    """Move global options found after the command to the front, so they work in either position.

    GitHub Actions and the plan call `nlead run monthly --env prod --segment clinics-in`; Click would
    otherwise only accept global options before the command name. Everything after `--` is left alone.
    """
    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            rest.extend(args[i:])
            break
        name, has_value = arg.split("=", 1)[0], "=" in arg
        if (name in GLOBAL_FLAG_OPTIONS and not has_value) or (name in GLOBAL_VALUE_OPTIONS and has_value):
            front.append(arg)
        elif name in GLOBAL_VALUE_OPTIONS and i + 1 < len(args):
            front.extend(args[i : i + 2])
            i += 1
        else:
            rest.append(arg)
        i += 1
    return front + rest


class NleadGroup(TyperGroup):
    """Root command group that accepts the global options anywhere on the command line."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:  # ctx: the Click context Typer passes
        return super().parse_args(ctx, hoist_global_options(list(args)))


_TYPER_SETTINGS: dict[str, Any] = {
    "no_args_is_help": True,
    "add_completion": False,
    "pretty_exceptions_show_locals": False,  # locals can hold connection strings; never print them
}

app = typer.Typer(
    cls=NleadGroup, help="Nument Leads engine: finds, researches, scores and writes leads.", **_TYPER_SETTINGS
)
extract_app = typer.Typer(
    help="AI fact extraction batches (submit at night, collect in the morning).", **_TYPER_SETTINGS
)
sheet_app = typer.Typer(help="Google Sheet two-way sync.", **_TYPER_SETTINGS)
report_app = typer.Typer(help="Reports.", **_TYPER_SETTINGS)
run_app = typer.Typer(help="Orchestrated runs used by GitHub Actions.", **_TYPER_SETTINGS)
db_app = typer.Typer(help="Database schema and configuration: migrations and segment sync.", **_TYPER_SETTINGS)
notify_app = typer.Typer(help="Email: send a sample, or write previews of every email.", **_TYPER_SETTINGS)
app.add_typer(extract_app, name="extract")
app.add_typer(sheet_app, name="sheet")
app.add_typer(report_app, name="report")
app.add_typer(run_app, name="run")
app.add_typer(db_app, name="db")
app.add_typer(notify_app, name="notify")


class Env(StrEnum):
    dev = "dev"
    prod = "prod"


def _check_segments(values: list[str] | None) -> list[str] | None:
    for value in values or []:
        if not SEGMENT_ID.match(value):
            raise typer.BadParameter(f"{value!r} is not a segment id like clinics-in")
    return values


@app.callback()
def main(
    ctx: typer.Context,
    env: Annotated[Env, typer.Option("--env", help="Environment to run against.")] = Env.dev,
    segment: Annotated[
        list[str] | None,
        typer.Option("--segment", help="Segment id, for example clinics-in. Repeatable.", callback=_check_segments),
    ] = None,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Max items per stage.")] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="No sheet or database writes for leads, no batch submission; sync AI calls still run within --max-spend-inr.",
        ),
    ] = False,
    max_spend_inr: Annotated[
        float | None,
        typer.Option("--max-spend-inr", min=0, help="Hard cap on paid AI and API calls for this run (INR)."),
    ] = None,
    json_logs: Annotated[bool, typer.Option("--json-logs/--pretty-logs", help="Log format.")] = True,
) -> None:
    """Nument Leads engine. Global flags work before or after the command."""
    ctx.obj = Options(env=env.value, segments=segment or [], limit=limit, dry_run=dry_run, max_spend_inr=max_spend_inr)
    ctx.meta["nlead.json_logs"] = json_logs


def _bootstrap(ctx: typer.Context) -> Options:
    """Load settings for --env (fail fast on a bad env file) and set up logging. Called by every command."""
    import os

    from pydantic import ValidationError

    from .logging import setup_logging
    from .settings import env_file_for, get_settings

    opts: Options = ctx.obj
    os.environ["APP_ENV"] = opts.env  # must happen before settings load
    get_settings.cache_clear()
    try:
        get_settings()
    except ValidationError as exc:
        typer.secho(f"Configuration error for APP_ENV={opts.env}:", err=True, fg=typer.colors.RED)
        for err in exc.errors():
            where = ".".join(str(part) for part in err["loc"]) or "settings"
            typer.echo(f"  - {where}: {err['msg']}", err=True)  # never echo err['input']: it may be a secret
        typer.echo(f"Check {env_file_for(opts.env)} or the environment variables.", err=True)
        raise typer.Exit(code=2) from None
    setup_logging(json_output=bool(ctx.meta.get("nlead.json_logs", True)))
    return opts


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.secho(message, err=True, fg=typer.colors.RED)
    return typer.Exit(code=code)


def _execute(ctx: typer.Context, kind: str, work: Callable[[RunContext], object]) -> None:
    """Run `work` inside a run context and turn known failures into clear messages and exit codes."""
    import psycopg
    import psycopg_pool

    from . import db
    from .pipeline.runs import EssentialPhaseFailed, run_context
    from .sheet.client import SheetsApiError
    from .sheet.push import SheetNotAdopted

    opts = _bootstrap(ctx)
    try:
        with run_context(kind, opts) as rc:
            work(rc)
    except NotImplementedError as exc:
        typer.secho(f"{ctx.command_path}: not built yet ({exc}).", err=True, fg=typer.colors.YELLOW)
        raise typer.Exit(code=2) from None
    except EssentialPhaseFailed as exc:
        raise _fail(f"{ctx.command_path}: {exc}. The run is marked failed; see runs.error for the traceback.") from None
    except (SheetNotAdopted, SheetsApiError) as exc:
        raise _fail(f"{ctx.command_path}: {exc}") from None
    except (psycopg.OperationalError, psycopg_pool.PoolTimeout) as exc:
        raise _fail(
            f"{ctx.command_path}: cannot reach the database ({type(exc).__name__}). "
            "Check DATABASE_URL (session pooler, port 5432) and that the Supabase project is not paused."
        ) from None
    finally:
        db.close_pool()


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


@app.command()
def universe(
    ctx: typer.Context,
    monthly: Annotated[bool, typer.Option("--monthly", help="Full refresh from the new monthly release.")] = False,
) -> None:
    """Build or refresh the universe from Overture, Places and registries (Step 6)."""
    from .pipeline import universe as m

    _execute(ctx, "manual", lambda rc: m.run(rc, monthly=monthly))


@app.command()
def signals(ctx: typer.Context) -> None:
    """Run all signal watchers (Step 7)."""
    from .pipeline import signals as m

    _execute(ctx, "manual", m.run)


@app.command()
def prefilter(ctx: typer.Context) -> None:
    """Apply the rules and build today's research queue (Step 8)."""
    from .pipeline import prefilter as m

    _execute(ctx, "manual", m.run)


@app.command()
def research(ctx: typer.Context) -> None:
    """Crawl queued businesses, store pages, detect tech (Step 9)."""
    from .pipeline import research as m

    _execute(ctx, "manual", m.run)


@extract_app.command("submit")
def extract_submit(ctx: typer.Context) -> None:
    """Submit the AI fact extraction batch (Step 9)."""
    from .pipeline import extract as m

    _execute(ctx, "manual", m.submit)


@extract_app.command("collect")
def extract_collect(ctx: typer.Context) -> None:
    """Collect the AI fact extraction batch (Step 9)."""
    from .pipeline import extract as m

    _execute(ctx, "manual", m.collect)


@app.command()
def verify(ctx: typer.Context) -> None:
    """Re-check quotes, phones and websites (Step 10)."""
    from .pipeline import verify as m

    _execute(ctx, "manual", m.run)


@app.command()
def reviews(ctx: typer.Context) -> None:
    """Public Google review numbers for researched businesses without Places data (the Places fallback)."""
    from .pipeline import reviews as m

    _execute(ctx, "manual", m.run)


@app.command("maps-reviews")
def maps_reviews(ctx: typer.Context) -> None:
    """Google Maps review numbers and review pain for tonight's businesses without Places data."""
    from .pipeline import maps_reviews as m

    _execute(ctx, "manual", m.run)


@app.command()
def score(
    ctx: typer.Context,
    all_businesses: Annotated[
        bool, typer.Option("--all", help="Also re-score dormant businesses, for example after a SCORE_VERSION bump.")
    ] = False,
) -> None:
    """Compute scores and grades, then create or update leads (Step 11)."""
    from .pipeline import score as m

    _execute(ctx, "manual", lambda rc: m.run(rc, all_businesses=all_businesses))


@app.command()
def lookup(ctx: typer.Context) -> None:
    """Official websites for businesses born from a job post or an ask (the need-first track)."""
    from .pipeline import lookup as m

    _execute(ctx, "manual", m.run)


@app.command()
def judge(ctx: typer.Context) -> None:
    """Top-model judgement for the top half (Step 11)."""
    from .pipeline import judge as m

    _execute(ctx, "manual", m.run)


@app.command()
def message(ctx: typer.Context) -> None:
    """Write, lint and check messages (Step 12)."""
    from .pipeline import message as m

    _execute(ctx, "manual", m.run)


# ---------------------------------------------------------------------------
# Sheet sync
# ---------------------------------------------------------------------------


LIGHT_HELP = "Rebuild Lead details only when leads were added or removed (the daytime schedule)."


@sheet_app.command("push")
def sheet_push(
    ctx: typer.Context,
    light: Annotated[bool, typer.Option("--light", help=LIGHT_HELP)] = False,
    resort: Annotated[bool, typer.Option("--resort", help="Re-rank every row, best first. Only on request.")] = False,
) -> None:
    """Database to sheet (Step 13). Honours --dry-run (build and validate, write nothing)."""
    from .sheet import push as m

    _execute(ctx, "sheet_sync", lambda rc: _record(rc, "push", m.run(rc, light=light, resort=resort)))


@sheet_app.command("pull")
def sheet_pull(
    ctx: typer.Context,
    seed_snapshots: Annotated[
        bool,
        typer.Option(
            "--seed-snapshots",
            help="Adopt sheets the old engine wrote: record a baseline, then pull (Step 20.6). Writes no lead data.",
        ),
    ] = False,
    legacy_root: Annotated[
        Path | None, typer.Option("--legacy-root", help="Old lead-engine folder (default ~/Desktop/lead-engine).")
    ] = None,
) -> None:
    """Sheet to database (Step 13). Honours --dry-run (report the edits, write nothing)."""
    from .sheet import pull as m

    _execute(
        ctx,
        "sheet_sync",
        lambda rc: _record(rc, "pull", m.run(rc, seed_snapshots=seed_snapshots, legacy_root=legacy_root)),
    )


@sheet_app.command("sync")
def sheet_sync(ctx: typer.Context, light: Annotated[bool, typer.Option("--light", help=LIGHT_HELP)] = False) -> None:
    """Pull people's edits, then push (Step 13)."""
    from .sheet import sync as m

    _execute(ctx, "sheet_sync", lambda rc: _record(rc, "sheet", m.run(rc, light=light)))


@sheet_app.command("render")
def sheet_render(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Folder for the PDFs.", file_okay=False)],
) -> None:
    """Export every tab of every view to PDF for a visual check (Step 13)."""
    from .sheet import render as m

    _execute(ctx, "manual", lambda rc: _echo_files(m.run(rc, out=out)))


@sheet_app.command("check")
def sheet_check(ctx: typer.Context) -> None:
    """Can the service account open each sheet this environment writes, and is it set up yet? (Step 13.4)"""
    import json

    from .sheet import client
    from .sheet import state as st

    _bootstrap(ctx)
    try:
        api = client.GoogleSheetsApi()
        rows = client.check_targets(api, st.states())
    except client.SheetsApiError as exc:
        raise _fail(f"sheet check: {exc}") from None
    finally:
        from . import db

        db.close_pool()
    for row in rows:
        typer.echo(json.dumps(row, ensure_ascii=False))
    if not all(r["ok"] for r in rows):
        raise typer.Exit(code=1)


def _record(rc: RunContext, key: str, stats: object) -> None:
    """Keep a command's stats in the run row and print them (one JSON line) for the person running it."""
    import json

    rc.stats[key] = stats
    typer.echo(json.dumps(stats, default=str, ensure_ascii=False))


def _echo_files(result: dict[str, list[str]]) -> None:
    for name in result.get("files", []):
        typer.echo(name)


# ---------------------------------------------------------------------------
# Learning, reports, evaluation, operations
# ---------------------------------------------------------------------------


@app.command()
def learn(
    ctx: typer.Context,
    rollback: Annotated[
        int | None, typer.Option("--rollback", min=1, metavar="VERSION", help="Restore an older weights version.")
    ] = None,
) -> None:
    """Weekly re-weighting from outcomes; --dry-run only proposes (Step 16.4)."""
    from .learn import reweight as m

    if rollback is not None:
        version = rollback

        def restore(rc: RunContext) -> None:
            try:
                new = m.rollback(version)
            except ValueError as exc:
                raise _fail(str(exc)) from None
            rc.stats["rollback"] = {"to": version, "new_version": new}
            typer.echo(f"Weights restored from version {version} as version {new}.")

        _execute(ctx, "manual", restore)
        return

    def propose(rc: RunContext) -> None:
        result = m.run(rc)
        typer.echo(f"Re-weighting: {result['status']}, {len(result['changes'])} change(s).")
        for c in result["changes"]:
            typer.echo(f"  {c['segment_id']} {c['key']}: {c['old']} to {c['new']} ({c['note']}, {c['trials']} leads)")

    _execute(ctx, "weekly", propose)


@report_app.command("weekly")
def report_weekly(
    ctx: typer.Context,
    week_start: Annotated[
        datetime | None,
        typer.Option("--week-start", formats=["%Y-%m-%d"], help="Monday of the week (default: last full week, IST)."),
    ] = None,
) -> None:
    """Build, store and deliver the weekly report; --dry-run prints it only (Step 16.6)."""
    from .learn import report as m

    start = week_start.date() if week_start else None
    if start is not None and start.weekday() != 0:
        raise typer.BadParameter(f"{start} is not a Monday", param_hint="--week-start")
    _execute(ctx, "weekly", lambda rc: m.weekly(rc, week_start=start))


@app.command()
def audit(ctx: typer.Context) -> None:
    """Weekly audit of 20 recent leads; --dry-run skips AI calls and stores nothing (Step 17.6)."""
    from .ops import audit as m

    _execute(ctx, "weekly", m.weekly)


def _load_evals() -> ModuleType:
    """engine/evals lives next to the package, not inside it; make it importable for the console script."""
    from .settings import ENGINE_DIR

    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    return importlib.import_module("evals.run_eval")


@app.command(name="eval")
def eval_(
    ctx: typer.Context,
    subset: Annotated[
        int | None, typer.Option("--subset", min=1, help="Evaluate N businesses; 20 uses the fixed CI subset.")
    ] = None,
    export_golden: Annotated[
        bool, typer.Option("--export-golden", help="Write labels, frozen pages and the subset from the database.")
    ] = False,
    replay: Annotated[
        Path | None, typer.Option("--replay", exists=True, dir_okay=False, help="Re-check saved outcomes, no AI.")
    ] = None,
    save_outcomes: Annotated[
        Path | None, typer.Option("--save-outcomes", dir_okay=False, help="Write each business's outcome (JSONL).")
    ] = None,
) -> None:
    """Golden-set evaluation. Exit 1: a threshold failed; 2: cannot run yet; 3: skipped for budget (Step 17.4)."""
    outcome: dict[str, Any] = {}

    def work(rc: RunContext) -> None:
        outcome.update(
            _load_evals().run(rc, subset=subset, export=export_golden, replay=replay, save_outcomes=save_outcomes)
        )

    _execute(ctx, "manual", work)
    if outcome.get("status") == "skipped_budget":
        raise _fail(f"eval skipped: budget ({outcome.get('detail')})", code=3)
    if outcome.get("status") == "failed":
        raise _fail("eval failed: at least one threshold was missed")


@app.command()
def health(
    ctx: typer.Context,
    prune: Annotated[bool, typer.Option("--prune", help="Apply the retention rules (Step 18.2.2).")] = False,
    summary: Annotated[bool, typer.Option("--summary", help="Markdown for the GitHub job summary.")] = False,
    notify: Annotated[bool, typer.Option("--notify", help="Email new alerts (when email is configured).")] = False,
    models: Annotated[
        bool, typer.Option("--models", help="Check every AI model id in tasks.yaml against the providers (Step 4.4).")
    ] = False,
    llm_smoke: Annotated[
        bool,
        typer.Option("--llm-smoke", help="One tiny paid request per AI task on every usable model (under ₹5)."),
    ] = False,
    providers: Annotated[
        str | None,
        typer.Option("--providers", help="With --models or --llm-smoke: providers to use, e.g. gemini,openai."),
    ] = None,
) -> None:
    """Check the database, AI providers, quotas, sources and runs. Exit 1 when a check fails (Step 22).

    --models and --llm-smoke check the AI router instead (Step 4.4 and 4.12).
    """
    if models or llm_smoke:
        from .llm import health as llm_health

        failures: list[int] = []

        def check(rc: RunContext) -> None:
            failures.append(llm_health.run(rc, models=models, smoke=llm_smoke, providers=providers))

        _execute(ctx, "manual", check)
        if failures and failures[0]:
            raise typer.Exit(code=1)
        return
    import psycopg
    import psycopg_pool

    from . import db
    from .ops import health as m

    if prune:
        _execute(ctx, "manual", m.prune_run)
        return
    _bootstrap(ctx)
    try:
        if summary:
            typer.echo(m.daily_summary())
            return
        checks = m.collect()
        typer.echo(m.render_text(checks))
        if notify:
            sent = m.notify_alerts()
            typer.echo(f"alerts: {len(sent['alerts'])}, new today: {len(sent['new'])}, emailed: {sent['emailed']}")
        if m.worst(checks) == "fail":
            raise typer.Exit(code=1)
    except (psycopg.OperationalError, psycopg_pool.PoolTimeout) as exc:
        raise _fail(
            f"{ctx.command_path}: cannot reach the database ({type(exc).__name__}). "
            "Check DATABASE_URL (session pooler, port 5432) and that the Supabase project is not paused."
        ) from None
    finally:
        db.close_pool()


@app.command()
def backup(
    ctx: typer.Context,
    out: Annotated[
        Path | None, typer.Option("--out", help="Where to write the encrypted dump (default: the engine cache folder).")
    ] = None,
) -> None:
    """Encrypted dump of the public schema to the private backups bucket (Step 14.5.6)."""
    from .ops import backup as m

    _execute(ctx, "manual", lambda rc: _record(rc, "backup", m.run(rc, out=out)))


@app.command(name="migrate-legacy")
def migrate_legacy(
    ctx: typer.Context,
    root: Annotated[
        Path | None, typer.Option("--root", help="Old lead-engine folder (default ~/Desktop/lead-engine). Read only.")
    ] = None,
) -> None:
    """One-time import from the old lead-engine folder (Step 20). Safe to re-run; --dry-run rolls back."""
    from .ops import migrate_legacy as m

    _execute(ctx, "manual", lambda rc: _record(rc, "migrate_legacy", m.run(rc, root=root)))


# ---------------------------------------------------------------------------
# Email (the morning list, alerts and the weekly report go out from the runs themselves)
# ---------------------------------------------------------------------------

EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SAMPLE_HELP = "Which email: morning, morning-empty, alert or weekly."


@notify_app.command("test")
def notify_test(
    ctx: typer.Context,
    to: Annotated[str, typer.Option("--to", help="Send the sample to this one address only.")],
    kind: Annotated[str, typer.Option("--kind", help=SAMPLE_HELP)] = "morning",
) -> None:
    """Send one sample email (made-up leads) through Resend, to check delivery and looks."""
    from .ops import emails, notify

    _bootstrap(ctx)
    address = to.strip().lower()
    if not EMAIL_ADDRESS.match(address):
        raise typer.BadParameter(f"{to!r} is not an email address", param_hint="--to")
    if kind not in emails.SAMPLE_KINDS:
        raise typer.BadParameter(f"choose one of {', '.join(emails.SAMPLE_KINDS)}", param_hint="--kind")
    if not notify.email_configured():
        raise _fail("RESEND_API_KEY is not set: nothing was sent.")
    sample = emails.sample(kind)
    sent = notify.send(notify.Email(f"[Test] {sample.subject}", sample.html, sample.text), [address])
    if not sent:
        raise _fail("Resend did not accept the email; see the log line above.")
    typer.echo(f"Sent the {kind} sample to {address}.")


@notify_app.command("preview")
def notify_preview(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Folder for the HTML and text files.", file_okay=False)],
) -> None:
    """Write every email as HTML and text with sample data, for the admin view and the team view. Sends nothing."""
    from .ops import emails

    _bootstrap(ctx)
    for path in emails.write_previews(out):
        typer.echo(path)


# ---------------------------------------------------------------------------
# Orchestrated runs (GitHub Actions)
# ---------------------------------------------------------------------------


@run_app.command("night")
def run_night(ctx: typer.Context) -> None:
    """02:00 IST: pipeline part 1 (Step 14)."""
    from .pipeline import runs

    _execute(ctx, "night", runs.night)


@run_app.command("morning")
def run_morning(ctx: typer.Context) -> None:
    """06:00 IST: pipeline part 2 (Step 14)."""
    from .pipeline import runs

    _execute(ctx, "morning", runs.morning)


@run_app.command("midday")
def run_midday(ctx: typer.Context) -> None:
    """13:00 IST: the day's new signals, lead stages and the hot-lead email (13 Nov 2026)."""
    from .pipeline import runs

    _execute(ctx, "midday", runs.midday)


@run_app.command("sheet")
def run_sheet(ctx: typer.Context, light: Annotated[bool, typer.Option("--light", help=LIGHT_HELP)] = False) -> None:
    """Daytime: late batch items at 09:00, then the two-way sheet sync (Step 14)."""
    from .pipeline import runs

    _execute(ctx, "sheet_sync", lambda rc: runs.sheet(rc, light=light))


@run_app.command("weekly")
def run_weekly(ctx: typer.Context) -> None:
    """Monday: learning, report, audit and page-text retention (Step 14)."""
    from .pipeline import runs

    _execute(ctx, "weekly", runs.weekly)


@run_app.command("monthly")
def run_monthly(ctx: typer.Context) -> None:
    """Monthly universe refresh and page-text retention (Step 14)."""
    from .pipeline import runs

    _execute(ctx, "monthly", runs.monthly)


# ---------------------------------------------------------------------------
# Database (not part of the scheduled pipeline)
# ---------------------------------------------------------------------------


@db_app.command("migrate")
def db_migrate(ctx: typer.Context) -> None:
    """Apply pending supabase/migrations to DATABASE_URL. Honours --dry-run.

    Records history in supabase_migrations.schema_migrations, the same table `supabase db push` uses.
    """
    import psycopg

    from .ops import migrate as m

    opts = _bootstrap(ctx)
    try:
        with m.connect() as conn:
            done = m.apply(conn, dry_run=opts.dry_run)
    except m.MigrationError as exc:
        raise _fail(f"Migration failed: {exc}") from None
    except psycopg.OperationalError as exc:
        raise _fail(f"Cannot reach the database ({type(exc).__name__}). Check DATABASE_URL.") from None
    verb = "Would apply" if opts.dry_run else "Applied"
    if not done:
        typer.echo("Database is up to date.")
    for mig in done:
        typer.echo(f"{verb} {mig.filename}")


@db_app.command("status")
def db_status(ctx: typer.Context) -> None:
    """List migrations and whether each one is applied."""
    import psycopg

    from .ops import migrate as m

    _bootstrap(ctx)
    try:
        with m.connect() as conn:
            rows = m.status(conn)
    except psycopg.OperationalError as exc:
        raise _fail(f"Cannot reach the database ({type(exc).__name__}). Check DATABASE_URL.") from None
    for mig, applied in rows:
        typer.echo(f"{'applied' if applied else 'pending':8} {mig.filename}")


@db_app.command("sync-segments")
def db_sync_segments(ctx: typer.Context) -> None:
    """Validate engine/segments/*.yaml and upsert them into public.segments. Honours --dry-run (validate only)."""
    from . import db
    from .segments import load_segments, sync_segments_to_db

    opts = _bootstrap(ctx)
    try:
        research_per_day = int(db.get_setting("research_per_day", 800))
        segments = load_segments(research_per_day=research_per_day)
        if opts.dry_run:
            typer.echo(f"Valid: {', '.join(sorted(segments))} (dry run, nothing written)")
            return
        with db.tx() as conn:
            count = sync_segments_to_db(conn, segments)
        typer.echo(f"Synced {count} segments: {', '.join(sorted(segments))}")
    finally:
        db.close_pool()


if __name__ == "__main__":
    app()
