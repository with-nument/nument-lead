"""Entity resolution (Step 6.6): matching rules 1 to 6, merges by source precedence, branches, statuses,
idempotency and merging two rows that turn out to be one company."""

from __future__ import annotations

from typing import Any

from nument_engine import db
from nument_engine.pipeline.resolve import Candidate, Resolver, candidate_from_hint, merge_businesses, name_score
from nument_engine.sources.base import SourceRecord

from .sources_helpers import clean_db, insert_business, no_network, segment

__all__ = ["clean_db", "no_network"]

SEG = segment()


def cand(source: str, key: str, name: str, **kw: Any) -> Candidate:
    kw.setdefault("city", "Pune")
    return Candidate(source=source, source_key=key, segment_id=SEG.id, name=name, **kw)


def business(bid: str) -> dict[str, Any]:
    row = db.fetch_one("select * from public.businesses where id = %s", [bid])
    assert row is not None
    return row


def test_rule_1_the_same_record_links_to_the_same_business(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, action = r.resolve(cand("overture", "ov-r1", "Smile Dental Studio", lat=18.56, lng=73.78)) or ("", "")
        assert action == "created"
    with Resolver(SEG) as r2:
        again = r2.resolve(cand("overture", "ov-r1", "Smile Dental Studio", lat=18.56, lng=73.78))
    assert again == (bid, "linked")
    assert db.scalar("select count(*) from public.businesses where name = 'Smile Dental Studio'") == 1


def test_rule_2_place_and_overture_ids(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, _ = r.resolve(cand("overture", "ov-r2", "Glow Skin", overture_id="ov-r2", lat=18.55, lng=73.79)) or (
            "",
            "",
        )
        assert r.resolve(cand("osm", "node/1", "Glow Skin Centre", overture_id="ov-r2")) == (bid, "matched")
        assert r.resolve(cand("places", "pl-r2", "Glow Skin Clinic", place_id="pl-r2", lat=18.55, lng=73.79)) == (
            bid,
            "matched",
        )
        assert r.resolve(cand("places", "pl-r2-b", "Glow", place_id="pl-r2")) == (bid, "matched")


def test_rule_3_domain_and_far_points_are_branches(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, _ = r.resolve(
            cand(
                "overture", "ov-r3a", "Bright Smile Dental", website="https://brightsmile-r3.in/", lat=18.50, lng=73.80
            )
        ) or ("", "")
        near = r.resolve(
            cand(
                "places",
                "pl-r3b",
                "Bright Smile Dental Baner",
                website="https://www.brightsmile-r3.in/x",
                lat=18.5005,
                lng=73.8005,
            )
        )
        far = r.resolve(
            cand(
                "places",
                "pl-r3c",
                "Bright Smile Dental Kothrud",
                website="https://brightsmile-r3.in/",
                lat=18.51,
                lng=73.81,
            )
        )
    assert near == (bid, "matched") and far == (bid, "branch")
    row = business(bid)
    assert row["branches_count"] == 2 and row["web_domain"] == "brightsmile-r3.in"
    assert db.scalar("select count(*) from public.source_records where business_id = %s", [bid]) == 3


def test_rule_4_phone_but_never_toll_free_or_shared_numbers(clean_db: str) -> None:
    with Resolver(SEG) as r:
        a, _ = r.resolve(
            cand(
                "places",
                "pl-r4a",
                "Pearl Dental",
                place_id="pl-r4a",
                contact_phones=[("+919811100001", "mobile")],
                contact_source="google_listing",
            )
        ) or ("", "")
        assert r.resolve(cand("overture", "ov-r4", "Pearl Dental Care", phone_hints=[("+919811100001", "mobile")])) == (
            a,
            "matched",
        )
        tollfree = r.resolve(cand("overture", "ov-r4t", "Other Clinic", phone_hints=[("+9118001234567", "tollfree")]))
        assert tollfree is not None and tollfree[1] == "created"
    # A call-centre number already published by 5 businesses never merges a sixth into them.
    for i in range(5):
        bid = insert_business(name=f"Franchise Outlet {i}")
        db.execute(
            "insert into public.contacts (business_id, phone_e164, phone_type, source) "
            "values (%s, '+919822200002', 'mobile', 'website')",
            [bid],
        )
    with Resolver(SEG) as r2:
        r2.load()
        assert "+919822200002" in r2.shared_phones
        sixth = r2.resolve(cand("overture", "ov-r4s", "Another Outlet", phone_hints=[("+919822200002", "mobile")]))
    assert sixth is not None and sixth[1] == "created"


def test_rule_5_name_and_distance(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, _ = r.resolve(
            cand("overture", "ov-r5", "Dr Mehta Skin and Hair Clinic", lat=18.5600, lng=73.7800, locality="Baner")
        ) or ("", "")
        same = r.resolve(cand("osm", "node/r5", "Dr. Mehta's Skin & Hair Clinic", lat=18.5610, lng=73.7805))
        far = r.resolve(cand("osm", "node/r5far", "Dr Mehta Skin and Hair Clinic", lat=18.5800, lng=73.7800))
        no_point = r.resolve(cand("apna", "apna:r5", "Dr Mehta Skin and Hair Clinic", locality="Baner"))
        other_locality = r.resolve(cand("apna", "apna:r5b", "Dr Mehta Skin and Hair Clinic", locality="Kothrud"))
        other_city = r.resolve(
            cand("apna", "apna:r5c", "Dr Mehta Skin and Hair Clinic", city="Mumbai", locality="Baner")
        )
    assert same == (bid, "matched")
    assert far is not None and far[1] == "created"  # 2.2 km away: another clinic with the same name
    assert no_point == (bid, "matched")  # 96+ and the same locality
    assert other_locality is not None and other_locality[1] == "created"
    assert other_city is not None and other_city[1] == "created"


def test_one_word_names_do_not_merge_unrelated_clinics() -> None:
    assert name_score("dental", "city dental") < 92
    assert name_score("dental smile", "dental smile") == 100


def test_merge_precedence_places_name_beats_overture_and_ratings_come_from_places(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, _ = r.resolve(
            cand(
                "overture",
                "ov-m1",
                "LOTUS SKIN CLINIC PVT LTD",
                overture_id="ov-m1",
                lat=18.559,
                lng=73.786,
                address="Baner Rd",
                category="dermatology",
                subcategory="dermatology",
            )
        ) or ("", "")
        r.resolve(
            cand(
                "places",
                "pl-m1",
                "Lotus Skin & Hair Clinic",
                place_id="pl-m1",
                overture_id="ov-m1",
                lat=18.5591,
                lng=73.7869,
                address="Office 2, Baner Road, Pune 411045",
                rating=4.6,
                review_count=312,
                category="skin_care_clinic",
            )
        )
        r.resolve(cand("osm", "node/m1", "Lotus", overture_id="ov-m1", lat=18.6, lng=73.9))
    row = business(bid)
    assert row["name"] == "Lotus Skin & Hair Clinic" and row["norm_name"] == "lotus skin and hair clinic"
    assert row["address"] == "Office 2, Baner Road, Pune 411045" and float(row["lat"]) == 18.5591
    assert row["category"] == "dermatology"  # the segment's Overture mapping outranks the Places type
    assert row["rating"] is not None and row["review_count"] == 312 and row["places_fetched_at"] is not None
    assert row["extra"]["src"] == {"name": "places", "geo": "places", "address": "places", "category": "overture"}


def test_listing_phones_and_registry_emails_become_contacts_and_hints_do_not(clean_db: str) -> None:
    rec = SourceRecord(
        source="art_registry",
        source_key="MH/AC/R1",
        segment_id=SEG.id,
        name="Hope IVF",
        emails=["care@hopeivf-nlead.in"],
        emails_are_registry=True,
        city="Pune",
        category="fertility_clinic",
        subcategory="ivf_fertility",
    )
    from nument_engine.pipeline.resolve import candidate_from_record

    with Resolver(SEG) as r:
        c = candidate_from_record(rec, SEG)
        assert c is not None
        bid, _ = r.resolve(c) or ("", "")
        r.resolve(
            cand("overture", "ov-c1", "Hope IVF Centre", phone_hints=[("+919833300003", "mobile")], overture_id="ov-c1")
        )
    contacts = db.fetch_all("select email, phone_e164, source from public.contacts where business_id = %s", [bid])
    assert contacts == [{"email": "care@hopeivf-nlead.in", "phone_e164": None, "source": "registry"}]
    assert business(bid)["extra"]["registries"] == {"art_registry": "MH/AC/R1"}


def test_closed_listings_go_dormant_and_come_back(clean_db: str) -> None:
    with Resolver(SEG) as r:
        bid, _ = r.resolve(cand("places", "pl-d1", "Closed Clinic", place_id="pl-d1", closed=True)) or ("", "")
    assert business(bid)["status"] == "dormant"
    with Resolver(SEG) as r:
        r.resolve(cand("places", "pl-d1", "Closed Clinic", place_id="pl-d1"))
    assert business(bid)["status"] == "candidate"


def test_running_twice_creates_nothing_new(clean_db: str) -> None:
    def build() -> list[tuple[str, str] | None]:
        with Resolver(SEG) as r:
            return [
                r.resolve(
                    cand(
                        "overture",
                        f"ov-i{i}",
                        f"Idempotent Clinic {i}",
                        lat=18.45 + i * 0.01,
                        lng=73.75,
                        overture_id=f"ov-i{i}",
                    )
                )
                for i in range(5)
            ]

    first, second = build(), build()
    assert all(x and x[1] == "created" for x in first)
    assert all(x and x[1] == "linked" for x in second)
    assert [x[0] for x in first if x] == [x[0] for x in second if x]


def test_dry_run_writes_nothing(clean_db: str) -> None:
    with Resolver(SEG, dry_run=True) as r:
        result = r.resolve(cand("overture", "ov-dry", "Dry Run Clinic", overture_id="ov-dry"))
    assert result is not None and result[1] == "created"
    assert db.scalar("select count(*) from public.businesses where name = 'Dry Run Clinic'") == 0


def test_hint_candidates_and_inbox_sources(clean_db: str) -> None:
    c = candidate_from_hint("inbox", "inbox:1", {"name": "Skin Theory", "city": "Pune"}, SEG)
    assert c is not None
    with Resolver(SEG) as r:
        res = r.resolve(c)
    assert res is not None and res[1] == "created"
    assert db.scalar("select count(*) from public.source_records where source_key = 'inbox:1'") == 0  # no raw record
    assert business(res[0])["extra"]["born_from"] == "inbox"
    assert candidate_from_hint("apna", "apna:x", {"name": ""}, SEG) is None


def test_merge_businesses_keeps_one_row_and_one_open_lead(clean_db: str) -> None:
    with Resolver(SEG) as r:
        keep, _ = r.resolve(cand("places", "pl-mg1", "Keep Clinic", place_id="pl-mg1", lat=18.5, lng=73.8)) or ("", "")
        drop, _ = r.resolve(
            cand(
                "overture",
                "ov-mg2",
                "Keep Clinic Kothrud",
                overture_id="ov-mg2",
                website="https://keepclinic-nlead.in/",
                lat=18.6,
                lng=73.9,
            )
        ) or ("", "")
    for bid in (keep, drop):
        score = db.scalar(
            "insert into public.scores (business_id, version, fit, total, grade, pitch_mode) "
            "values (%s, 'v1', 3, 70, 'A', 'visible_pain') returning id",
            [bid],
        )
        db.execute(
            "insert into public.leads (business_id, segment_id, score_id, grade, pitch_mode) "
            "values (%s, 'clinics-in', %s, 'A', 'visible_pain')",
            [bid, score],
        )
    out = merge_businesses(keep, drop)
    assert db.scalar("select count(*) from public.businesses where id = %s", [drop]) == 0
    stages = sorted(r["stage"] for r in db.fetch_all("select stage from public.leads where business_id = %s", [keep]))
    assert stages == ["new", "not_a_fit"]
    row = business(keep)
    assert row["web_domain"] == "keepclinic-nlead.in" and row["overture_id"] == "ov-mg2"
    assert drop in row["extra"]["merged_from"] and out["survivor_lead"]
    merges = db.scalar(
        "select count(*) from public.activities a join public.leads l on l.id = a.lead_id "
        "where l.business_id = %s and a.type = 'merge'",
        [keep],
    )
    assert merges == 2


def test_a_chain_across_cities_takes_the_city_of_most_branches(clean_db: str) -> None:
    """Live finding 12 Nov: a Bengaluru aligner chain was filed under Delhi, the city of its first branch."""
    from nument_engine.pipeline.message import single_city

    site = "https://whistle-r3x.in/"
    with Resolver(SEG) as r:
        bid, _ = r.resolve(
            cand("overture", "ov-cx1", "Whistle Aligners", website=site, city="Delhi", lat=28.6, lng=77.2)
        ) or (
            "",
            "",
        )
        for i, (lat, lng) in enumerate([(12.90, 77.58), (12.95, 77.60), (13.05, 77.55)]):
            r.resolve(
                cand("overture", f"ov-cx{i + 2}", "Whistle Aligners", website=site, city="Bengaluru", lat=lat, lng=lng)
            )
    row = business(bid)
    assert row["city"] == "Bengaluru"
    assert row["extra"]["city_counts"] == {"Delhi": 1, "Bengaluru": 3}
    assert single_city(row) == ""  # the message names no city for a chain spread over cities
    assert single_city({"city": "Pune", "extra": {"city_counts": {"Pune": 4}}}) == "Pune"


def test_a_job_post_without_a_point_matches_the_one_business_of_that_name_in_its_city(clean_db: str) -> None:
    """Live finding 12 Nov: Apna hiring signals created bare duplicates of clinics already in the universe."""
    with Resolver(SEG) as r:
        known, _ = r.resolve(
            cand(
                "overture", "ov-cn1", "Dralisdentacare", website="https://dralisdentacare-cn.com/", lat=18.52, lng=73.85
            )
        ) or ("", "")
        r.resolve(cand("overture", "ov-cn2", "Dental Clinic", lat=18.53, lng=73.86))
        r.resolve(cand("overture", "ov-cn3", "Dental Clinic", lat=18.60, lng=73.90))
        job = r.resolve(cand("apna", "apna:cn-1", "Dr. Ali's Dentacare"))
        generic = r.resolve(cand("apna", "apna:cn-2", "Dental Clinic"))
        other_city = r.resolve(cand("apna", "apna:cn-3", "Dr. Ali's Dentacare", city="Mumbai"))
    assert job == (known, "matched") and r.stats["rule.compact_name"] == 1
    assert generic is not None and generic[1] == "created"  # too common to pick one clinic
    assert other_city is not None and other_city[1] == "created"
