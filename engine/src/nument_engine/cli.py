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
from enum import StrEnum
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
app.add_typer(extract_app, name="extract")
app.add_typer(sheet_app, name="sheet")
app.add_typer(report_app, name="report")
app.add_typer(run_app, name="run")
app.add_typer(db_app, name="db")


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
        bool, typer.Option("--dry-run", help="No sheet writes, no batch submission, no paid calls.")
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
    from .pipeline.runs import run_context

    opts = _bootstrap(ctx)
    try:
        with run_context(kind, opts) as rc:
            work(rc)
    except NotImplementedError as exc:
        typer.secho(f"{ctx.command_path}: not built yet ({exc}).", err=True, fg=typer.colors.YELLOW)
        raise typer.Exit(code=2) from None
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
def score(ctx: typer.Context) -> None:
    """Compute scores and grades (Step 11)."""
    from .pipeline import score as m

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


@sheet_app.command("push")
def sheet_push(ctx: typer.Context) -> None:
    """Database to sheet (Step 13)."""
    from .sheet import push as m

    _execute(ctx, "sheet_sync", m.run)


@sheet_app.command("pull")
def sheet_pull(ctx: typer.Context) -> None:
    """Sheet to database (Step 13)."""
    from .sheet import pull as m

    _execute(ctx, "sheet_sync", m.run)


def _sheet_sync(rc: RunContext) -> None:
    from .sheet import pull, push

    pull.run(rc)  # always pull people's edits first
    push.run(rc)


@sheet_app.command("sync")
def sheet_sync(ctx: typer.Context) -> None:
    """Pull people's edits, then push (Step 13)."""
    _execute(ctx, "sheet_sync", _sheet_sync)


# ---------------------------------------------------------------------------
# Learning, reports, evaluation, operations
# ---------------------------------------------------------------------------


@app.command()
def learn(ctx: typer.Context) -> None:
    """Weekly re-weighting from outcomes (Step 16)."""
    from .learn import reweight as m

    _execute(ctx, "weekly", m.run)


@report_app.command("weekly")
def report_weekly(ctx: typer.Context) -> None:
    """Build and store the weekly report (Step 16)."""
    from .learn import report as m

    _execute(ctx, "weekly", m.weekly)


@app.command()
def audit(ctx: typer.Context) -> None:
    """Weekly audit of 20 recent leads (Step 17)."""
    from .learn import metrics as m

    _execute(ctx, "weekly", m.audit)


def _load_evals() -> ModuleType:
    """engine/evals lives next to the package, not inside it; make it importable for the console script."""
    from .settings import ENGINE_DIR

    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    return importlib.import_module("evals.run_eval")


@app.command(name="eval")
def eval_(
    ctx: typer.Context,
    subset: Annotated[int | None, typer.Option("--subset", min=1, help="Only the first N golden labels.")] = None,
) -> None:
    """Run the golden-set evaluation (Step 17)."""
    _execute(ctx, "manual", lambda rc: _load_evals().run(rc, subset=subset))


@app.command()
def health(
    ctx: typer.Context,
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
    """Check every service and source (Step 22). --models and --llm-smoke check the AI router (Step 4)."""
    if models or llm_smoke:
        from .llm import health as llm_health

        failures: list[int] = []

        def check(rc: RunContext) -> None:
            failures.append(llm_health.run(rc, models=models, smoke=llm_smoke, providers=providers))

        _execute(ctx, "manual", check)
        if failures and failures[0]:
            raise typer.Exit(code=1)
        return
    from .ops import health as m

    _execute(ctx, "manual", m.run)


@app.command()
def backup(ctx: typer.Context) -> None:
    """Encrypted dump of the public schema to the private backups bucket (Step 14.5.6)."""
    from .ops import backup as m

    _execute(ctx, "manual", m.run)


@app.command(name="migrate-legacy")
def migrate_legacy(ctx: typer.Context) -> None:
    """One-time import from the old lead-engine folder (Step 20)."""
    from .ops import migrate_legacy as m

    _execute(ctx, "manual", m.run)


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


@run_app.command("sheet")
def run_sheet(ctx: typer.Context) -> None:
    """Daytime two-way sheet sync (Step 14)."""
    _execute(ctx, "sheet_sync", _sheet_sync)


def _weekly(rc: RunContext) -> None:
    from .learn import metrics, report, reweight

    reweight.run(rc)
    report.weekly(rc)
    metrics.audit(rc)


@run_app.command("weekly")
def run_weekly(ctx: typer.Context) -> None:
    """Monday: learning, report and audit (Step 14)."""
    _execute(ctx, "weekly", _weekly)


@run_app.command("monthly")
def run_monthly(ctx: typer.Context) -> None:
    """Monthly universe refresh (Step 14)."""
    from .pipeline import universe as m

    _execute(ctx, "monthly", lambda rc: m.run(rc, monthly=True))


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
        research_per_day = int(db.get_setting("research_per_day", 300))
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
