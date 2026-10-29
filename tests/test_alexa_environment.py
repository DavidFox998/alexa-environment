import json

import pytest
from runway.client import ProposalError
from runway.receipts import ReceiptChain
from runway.run import replay as runway_replay

from alexa_env import receipts_view as view
from alexa_env.catalog import demo_catalog
from alexa_env.consent import ConsentMeasurement
from alexa_env.household import MandateBook, demo_book
from alexa_env.runner import HouseholdRunner
from alexa_env.skill import SkillHandler
from alexa_env.tenant_alexa import AlexaTenant


@pytest.fixture()
def setup(tmp_path):
    book = demo_book()
    runner = HouseholdRunner(book, demo_catalog(), tmp_path / "runs")
    return book, runner


def yes(speaker="dana", item="paper towels 12-pack", total=2410, **kw):
    return ConsentMeasurement(kw.get("recognized", True), speaker,
                              kw.get("confirmed", True), item, total)


# ---------------------------------------------------------------- settle
def test_settle_end_to_end(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    assert r.outcome == "PENDING_CONFIRMATION"
    assert "$24.10" in r.speech and "$28.00" in r.speech
    r = runner.confirm(r.run_id, yes())
    assert r.outcome == "SETTLED"
    assert book.mandates["towels-standing"].spent_cents == 2410
    chain = view.load_chain(r.receipt_path)
    assert chain.verify()
    assert "Bought" in view.explain(r.receipt_path)


def test_replay_bit_for_bit(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes())
    chain = view.load_chain(r.receipt_path)
    mandate = book.mandates["towels-standing"].run_mandate()
    rep = runway_replay(r.receipt_path, mandate)
    assert rep.outcome == "SETTLED"
    assert rep.receipt_head_hash == chain.entries[-1].hash


# ---------------------------------------------------------------- gates
def test_drift_refused_over_cap(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack",
                     listing_hint="towels-12-drift")
    # Confirmation cites the MEASURED price, not the asserted one.
    assert "$31.40" in r.speech and "$24.10" not in r.speech
    r = runner.confirm(r.run_id, yes(total=3140))
    assert r.outcome == "REFUSED" and r.refusal_reason == "over_cap"
    assert "over your $28.00 cap" in r.speech
    assert book.mandates["towels-standing"].spent_cents == 0


def test_unmeasured_refused_without_consent(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack",
                     listing_hint="towels-12-ghost")
    assert r.outcome == "REFUSED" and r.refusal_reason == "unmeasured"


def test_attribute_drift_refused(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack",
                     listing_hint="towels-12-offbrand")
    r = runner.confirm(r.run_id, yes(total=2200))
    assert r.outcome == "REFUSED"
    assert r.refusal_reason == "attribute_mismatch:brand"


def test_standing_budget_accumulates(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    runner.confirm(r.run_id, yes())
    # Second order: only $3.90 of the period budget remains.
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes())
    assert r.outcome == "REFUSED" and r.refusal_reason == "over_cap"
    assert "over the cap you set" in r.speech  # cumulative, in household words
    assert book.mandates["towels-standing"].spent_cents == 2410


# ---------------------------------------------------------------- custody
def test_custody_speaker_not_authorized(setup):
    book, runner = setup
    kit = book.speakers["kit"]
    r = runner.begin(kit, "paper towels 12-pack")
    assert r.outcome == "REFUSED"
    assert r.refusal_reason == "custody_speaker_not_authorized"
    assert view.load_chain(r.receipt_path).verify()  # refusal is receipted


def test_custody_no_mandate(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "a pony")
    assert r.outcome == "REFUSED" and r.refusal_reason == "custody_no_mandate"


def test_tenant_silence_is_recorded_not_invented(setup):
    book, runner = setup
    kit = book.speakers["kit"]   # fruit snacks: mandated, not in catalog
    r = runner.begin(kit, "fruit snacks")
    assert r.outcome == "ABORTED" and r.refusal_reason == "tenant_silent"
    assert "didn't guess" in r.speech


# ---------------------------------------------------------------- consent
def test_consent_total_mismatch(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes(total=2000))
    assert r.outcome == "REFUSED"
    assert r.refusal_reason == "consent_total_mismatch"
    assert r.refusal_gate == "consent"


def test_consent_unconfirmed_and_unrecognized(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes(confirmed=False))
    assert r.refusal_reason == "consent_unconfirmed"
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes(recognized=False))
    assert r.refusal_reason == "consent_speaker_unrecognized"


# ---------------------------------------------------------------- tenant
def test_tenant_contract():
    tenant = AlexaTenant(demo_catalog())
    book = demo_book()
    claim = tenant.propose_offer(book.mandates["towels-standing"].mandate)
    assert claim.kind == "offer" and claim.measurement is None
    assert claim.asserted_by.startswith("alexa:")
    assert claim.verdict_status == "pending"
    with pytest.raises(ProposalError):
        tenant.propose_offer(
            type("M", (), {"item": "unobtainium"})())


# ---------------------------------------------------------------- tamper
def test_tampered_receipt_refuses_replay(setup):
    book, runner = setup
    dana = book.speakers["dana"]
    r = runner.begin(dana, "paper towels 12-pack")
    r = runner.confirm(r.run_id, yes())
    lines = open(r.receipt_path).read().splitlines()
    entry = json.loads(lines[1])
    entry["payload"]["op"] = "FORGED"
    lines[1] = json.dumps(entry, sort_keys=True)
    open(r.receipt_path, "w").write("\n".join(lines) + "\n")
    chain = ReceiptChain.from_jsonl(open(r.receipt_path).read())
    assert not chain.verify()
    with pytest.raises(ValueError):
        view.explain(r.receipt_path)


# ---------------------------------------------------------------- book io
def test_book_round_trip(tmp_path):
    book = demo_book()
    book.mandates["towels-standing"].spent_cents = 500
    path = tmp_path / "book.json"
    book.save(path)
    loaded = MandateBook.load(path)
    assert loaded.mandates["towels-standing"].spent_cents == 500
    hm, reason = loaded.resolve(loaded.speakers["sam"],
                                "paper towels 12-pack")
    assert hm is not None and reason is None


# ---------------------------------------------------------------- skill
def _envelope(intent_name, user="amzn-user-dana", slots=None,
              session="s1", req_type="IntentRequest"):
    env = {"session": {"sessionId": session},
           "context": {"System": {"user": {"userId": user}}},
           "request": {"type": req_type}}
    if req_type == "IntentRequest":
        env["request"]["intent"] = {"name": intent_name,
                                    "slots": slots or {}}
    return env


def test_skill_two_phase_order(setup):
    book, runner = setup
    skill = SkillHandler(book, runner)
    resp = skill.handle(_envelope(
        "OrderIntent",
        slots={"Item": {"value": "paper towels 12-pack"}}))
    speech = resp["response"]["outputSpeech"]["text"]
    assert "$24.10" in speech
    assert resp["response"]["shouldEndSession"] is False
    resp = skill.handle(_envelope("AMAZON.YesIntent"))
    speech = resp["response"]["outputSpeech"]["text"]
    assert speech.startswith("Ordered")
    assert book.mandates["towels-standing"].spent_cents == 2410


def test_skill_unknown_speaker_stops(setup):
    book, runner = setup
    skill = SkillHandler(book, runner)
    resp = skill.handle(_envelope(
        "OrderIntent", user="amzn-user-stranger",
        slots={"Item": {"value": "paper towels 12-pack"}}))
    assert "couldn't confirm who is speaking" in \
        resp["response"]["outputSpeech"]["text"]
