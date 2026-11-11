"""The sorting checks, written once and run by BOTH live suites (each suite's
test module binds `client` + `provider`)."""
from tests.claude import cases
from tests.claude.harness import drop, first, folder_of, label_png, make_pdf, types


def _planned(entry):
    assert folder_of(entry).startswith("fun/travel/planned"), f"folder={entry.get('folder')!r}"


def check_trip_plan_pdf(c, provider):
    r = drop(c, data=make_pdf(cases.TRIP_PLAN), filename="lisbon_plan.pdf", provider=provider)
    assert "document_entry" not in types(r), types(r)
    _planned(first(r, "kb_entry"))


def check_trip_plan_md(c, provider):
    r = drop(c, data="\n\n".join(cases.TRIP_PLAN).encode(), filename="lisbon_plan.md", provider=provider)
    _planned(first(r, "kb_entry"))


def check_eticket_pdf(c, provider):
    r = drop(c, data=make_pdf(cases.TICKET), filename="eticket.pdf", provider=provider)
    assert "document_entry" not in types(r), types(r)
    _planned(first(r, "kb_entry"))


def check_passport_pdf(c, provider):
    first(drop(c, data=make_pdf(cases.PASSPORT), filename="passport_scan.pdf", provider=provider), "document_entry")


def check_insurance_pdf(c, provider):
    first(drop(c, data=make_pdf(cases.INSURANCE), filename="auto_policy.pdf", provider=provider), "document_entry")


def check_lecture_notes(c, provider):
    r = drop(c, data=cases.LECTURE.encode(), filename="raft_lecture.md", provider=provider)
    e = first(r, "kb_entry")
    assert not folder_of(e).startswith("fun/travel"), e.get("folder")
    assert "document_entry" not in types(r)


def check_journal_line(c, provider):
    t = types(drop(c, text=cases.JOURNAL_LINE, provider=provider))
    assert "exercise" in t and "finance" in t, t


def check_meal_plan(c, provider):
    t = types(drop(c, text=cases.MEAL_PLAN, provider=provider))
    assert "meal_composition" in t, t


def check_label_photo(c, provider):
    r = drop(c, data=label_png(cases.LABEL), filename="label.png", provider=provider)
    entries = [e for e in r.get("entries", []) if e.get("kcal") is not None]
    assert entries, f"no nutrition reading; got {types(r)} pipeline={r.get('pipeline')}"
    e = entries[0]
    got = {k: e.get(k) for k in cases.LABEL_EXPECT}
    assert all(abs(float(got[k] or 0) - v) <= 0.5 for k, v in cases.LABEL_EXPECT.items()), got
    return r


ALL = [check_trip_plan_pdf, check_trip_plan_md, check_eticket_pdf, check_passport_pdf, check_insurance_pdf,
       check_lecture_notes, check_journal_line, check_meal_plan, check_label_photo]
