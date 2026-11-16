"""The email as it leaves: footer, opt-out link, Re: subjects, placeholder and link rules, dev sandbox (E5a)."""

from __future__ import annotations

import re

import pytest

from nument_engine.outreach import compose as c

APP = "https://lead.nument.in"
ADDRESS = "Nument, 12 Example Road, Pune 411001, India"
THREAD = "6f1f8a52-0d7e-4a8e-9a3e-2b9c6c1d2e3f"


def _compose(**overrides: object) -> c.Composed:
    args: dict[str, object] = {
        "thread_id": THREAD,
        "to_email": "maya@acme.example.com",
        "subject": "Quick question about Acme",
        "body": "Hi Maya,\n\nSaw your launch on Hacker News. Who builds the app today?  \n\n",
        "step": 0,
        "mailbox": "hello.nument@gmail.com",
        "app_url": APP,
        "postal_address": ADDRESS,
        "production": True,
        "sandbox_to": None,
    }
    args.update(overrides)
    return c.compose(**args)  # type: ignore[arg-type]


def test_footer_has_signature_address_and_one_opt_out_line() -> None:
    out = _compose()
    assert out.body == (
        "Hi Maya,\n\nSaw your launch on Hacker News. Who builds the app today?\n\n"
        "Team Nument\n"
        f"{ADDRESS}\n"
        f"If you'd rather not hear from us, you can opt out here: {APP}/u/{THREAD}\n"
    )
    assert out.unsubscribe_url == f"{APP}/u/{THREAD}"
    assert out.unsubscribe_mailto == "mailto:hello.nument@gmail.com?subject=unsubscribe"
    assert out.to == "maya@acme.example.com" and not out.sandboxed
    assert c.has_footer(out.body, ADDRESS, out.unsubscribe_url)


def test_multi_line_postal_address_becomes_one_line() -> None:
    assert c.footer("Nument\n  12 Example Road \n\nPune", "https://x.nument.in/u/1").splitlines()[1] == (
        "Nument, 12 Example Road, Pune"
    )


@pytest.mark.parametrize("address", [None, "", "   \n "])
def test_no_postal_address_means_no_send(address: str | None) -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(postal_address=address)
    assert err.value.reason == "no_footer"


@pytest.mark.parametrize("app_url", ["", "http://lead.nument.in", "lead.nument.in"])
def test_opt_out_link_needs_an_https_app_url(app_url: str) -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(app_url=app_url)
    assert err.value.reason == "no_footer"


def test_trailing_slash_in_app_url() -> None:
    assert c.unsubscribe_url("https://lead.nument.in/", "t1") == "https://lead.nument.in/u/t1"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Quick question", "Re: Quick question"),
        ("Re: Quick question", "Re: Quick question"),
        ("RE:Quick question", "RE:Quick question"),
        ("Aw: Frage", "Aw: Frage"),
        ("  Quick   question ", "Re: Quick question"),
        ("Regarding the app", "Re: Regarding the app"),  # "Re" only as a prefix with a colon
    ],
)
def test_reply_subject(subject: str, expected: str) -> None:
    assert c.reply_subject(subject) == expected


def test_reply_subject_needs_a_subject() -> None:
    with pytest.raises(c.ComposeError, match="subject"):
        c.reply_subject("  ")


@pytest.mark.parametrize(
    "text",
    [
        "Here is your plan: {plan_link}",
        "See {case_study} for more",
        "Hi {{first_name}},",
        "Hi [First Name], quick one",
        "How is [Company] doing?",
        "Cheers, [Your Name]",
        "Hi { name },",
    ],
)
def test_placeholders_block_the_send(text: str) -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(body=text, step=3)
    assert err.value.reason == "placeholder"


def test_placeholder_in_the_subject_blocks_too() -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(subject="Idea for {company}")
    assert err.value.reason == "placeholder"


def test_ordinary_brackets_are_not_placeholders() -> None:
    assert c.placeholders("We shipped it [in two weeks] and (fast).") == []


@pytest.mark.parametrize(
    "body",
    [
        "Have a look at https://nument.in/work",
        "Our site: www.nument.in",
        "See nument.in for examples",
        "Try acme.app/demo first",
        "Built on vercel.app.",
        "http://example.com",
    ],
)
def test_day_zero_carries_no_link(body: str) -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(body=body)
    assert err.value.reason == "link_in_day0"
    _compose(body=body, step=3)  # a follow-up may carry a link


@pytest.mark.parametrize(
    "body",
    [
        "Reply to hello@nument.in if easier.",  # an address is not a link
        "We use Node.js and Next.js, e.g. for dashboards, i.e. the boring parts.",
        "Version 3.5 is out. The U.S. team agrees.",
        "It took 2.5 weeks.",
    ],
)
def test_text_that_is_not_a_link(body: str) -> None:
    assert c.links(body) == []
    _compose(body=body)


def test_link_in_day_zero_subject() -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(subject="nument.in has an idea for you")
    assert err.value.reason == "link_in_day0"


def test_empty_body_and_missing_day_zero_subject() -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(body="  \n ")
    assert err.value.reason == "empty_body"
    with pytest.raises(c.ComposeError) as err:
        _compose(subject=" ")
    assert err.value.reason == "no_subject"


def test_dev_rewrites_every_recipient_to_the_sandbox() -> None:
    out = _compose(production=False, sandbox_to="founder.sandbox@example.com")
    assert out.to == "founder.sandbox@example.com" and out.sandboxed
    assert out.subject == "Quick question about Acme"  # the content is what production would send


@pytest.mark.parametrize("sandbox", [None, "", "not-an-address"])
def test_dev_without_a_sandbox_sends_nothing(sandbox: str | None) -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(production=False, sandbox_to=sandbox)
    assert err.value.reason == "no_sandbox"


def test_production_needs_a_valid_recipient() -> None:
    with pytest.raises(c.ComposeError) as err:
        _compose(to_email="not an address")
    assert err.value.reason == "bad_address"


def test_rfc_message_ids_are_unique_and_well_formed() -> None:
    ids = {c.new_rfc_message_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(re.fullmatch(r"<[0-9a-f-]{36}@nument\.in>", i) for i in ids)


def test_country_codes_turn_yaml_booleans_back_into_codes() -> None:
    # YAML 1.1 reads a bare `no` (Norway) as false.
    assert c.country_codes(["DE", False, " at ", None, ""]) == {"de", "no", "at"}
