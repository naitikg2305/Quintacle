"""Inputs + the RIGHT answers, shared by tests/claude/local (qwen) and
tests/claude/subscription_or_api (Claude via Max). Expectations are fixed
up front; a failure is a finding about the model/code, never a reason to
re-fit the expectation."""

SEED_NOTES = [
    ("Fun/Travel/Planned/Japan", "Tokyo spring plan", "Draft plan for Tokyo in April: Shinjuku, Asakusa, day trip to Nikko."),
    ("Fun/Travel/Experiences/Portugal", "Lisbon weekend", "Visited Lisbon: Alfama, Belem, pasteis de nata."),
    ("Fun/Travel/Bucket List", "Patagonia", "Someday: Torres del Paine trek."),
    ("Knowledge/Tech Notes", "SQLite and threads", "One shared connection needs a lock across threads."),
    ("Documents", "Lease 2026", "Apartment lease, renews every August."),
]


def seed(c):
    """CLAUDE.md: model-quality tests run on preset-seeded data."""
    for name, kcal, p, cbs, f in [("Chicken rice bowl", 650, 45, 70, 15), ("Greek yogurt bowl", 320, 25, 35, 8)]:
        assert c.post("/logs/meals", json={"name": name, "kcal": kcal, "protein_g": p, "carbs_g": cbs, "fat_g": f}).status_code == 200
    assert c.post("/logs/routines", json={"name": "Push day", "exercises": ["Bench press", "Overhead press", "Dips"]}).status_code == 200
    for folder, title, content in SEED_NOTES:
        r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": content})
        assert r.status_code == 200, r.text


TRIP_PLAN = [
    "LISBON + PORTO | JUNE 2027 | TRIP PLAN",
    "7 days, one traveler. Fly Dulles (IAD) to Lisbon (LIS) Thu Jun 3, return from Porto (OPO) Jun 10.",
    "Flights I would target: TAP Air Portugal TP204 IAD-LIS, booking status: not booked.",
    "Hotels: Memmo Alfama (Lisbon, 4 nights), PortoBay Flores (Porto, 3 nights).",
    "Day 1 Lisbon: Alfama walk, Miradouro de Santa Luzia, fado dinner.",
    "Day 2 Lisbon: Belem tower, Jeronimos monastery, LX Factory.",
    "Day 4: train Lisbon to Porto, Alfa Pendular 2h50.",
    "Budget: roughly $2,100-3,000 excluding flights.",
]

TICKET = [
    "E-TICKET RECEIPT AND ITINERARY",
    "Passenger: GUPTA/NAITIK MR",
    "Booking reference: QK7M2L   Ticket number: 047 2391884410",
    "TP 204  Washington Dulles (IAD) 18:05 -> Lisbon (LIS) 06:50 +1  Economy",
    "TP 1947  Porto (OPO) 11:20 -> Lisbon (LIS) 12:15",
    "Baggage: 1PC. Check-in closes 60 minutes before departure.",
]

PASSPORT = [
    "UNITED STATES OF AMERICA  PASSPORT",
    "Type P  Code USA  Passport No. 912345678",
    "Surname DOE  Given names JANE",
    "Date of birth 14 MAR 1990  Place of birth VIRGINIA, U.S.A.",
    "Date of issue 02 JAN 2020  Date of expiration 01 JAN 2030",
    "Authority United States Department of State",
]

INSURANCE = [
    "GEICO Auto Insurance Policy Declarations",
    "Policy number 4412-88-190  Policy period 06/01/2026 - 12/01/2026",
    "Named insured: Jane Doe  Vehicle: 2021 Honda Civic",
    "Coverage: Bodily injury 100/300, Collision $500 deductible",
]


LECTURE = (
    "Lecture 7 - Distributed systems: Raft consensus. Leader election uses randomized timeouts; "
    "log entries are committed once replicated on a majority. Compare with Paxos: same safety, "
    "Raft is easier to reason about. Read the Ongaro paper section 5."
)

JOURNAL_LINE = "did push day at the gym, bench 3x8 at 80kg, then coffee at Compass for $6"

MEAL_PLAN = (
    "Lamb dinner plan:\n- 200g lamb shoulder\n- 150g basmati rice (cooked)\n- 100g greek yogurt\n"
    "- 1 cucumber\nTotal: about 900 kcal, 60g protein, 80g carbs, 35g fat"
)

# A nutrition label photo: every number is printed, so the reading must match exactly.
LABEL = [
    "Nutrition Facts",
    "Greek Nonfat Yogurt Plain",
    "Serving size 1 container (170g)",
    "Calories 90",
    "Total Fat 0g",
    "Sodium 60mg",
    "Total Carbohydrate 6g",
    "Total Sugars 4g",
    "Protein 16g",
    "Calcium 190mg",
]
LABEL_EXPECT = {"kcal": 90, "protein_g": 16, "carbs_g": 6, "fat_g": 0}
