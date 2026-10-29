"""The household runner: one order, end to end.

    speaker speaks → CUSTODY (whose mandate?) → tenant proposes →
    instrument measures → CONSENT (did the principal agree to
    THIS, at the measured total?) → environment gates → settle or
    named refusal → receipt sealed either way.

Two doctrines worth naming in the code:

- Consent gates settlement, not refusal. If the claim is
  unmeasurable, the runner submits it at once and lets the core
  gate refuse it — no confirmation is needed to say no.
- Pre-gate refusals (custody, consent) are sealed through the
  environment's own refusal path, so a custody refusal leaves the
  same kind of receipt as a gate refusal: RUN_REFUSED with the
  gate and the named reason, holds released, chain verifiable.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

from runway.client import ProposalError
from runway.gates import Verdict
from runway.receipts import ReceiptChain
from runway.run import Environment
from runway.tenant import Tenant

from . import receipts_view as view
from .catalog import FixtureCatalog
from .consent import ConsentMeasurement, check_consent
from .household import MandateBook, Speaker
from .tenant_alexa import AlexaTenant


@dataclass
class HouseholdResult:
    run_id: str
    outcome: str            # SETTLED | REFUSED | ABORTED | PENDING_CONFIRMATION
    speech: str
    card: dict
    receipt_path: str | None = None
    refusal_gate: str | None = None
    refusal_reason: str | None = None
    measured_cents: int | None = None


@dataclass
class _Pending:
    env: Environment
    claim: object
    measurement: object
    household_mandate: object
    speaker: Speaker
    item_text: str


class HouseholdRunner:
    def __init__(self, book: MandateBook, catalog: FixtureCatalog,
                 receipts_dir: str | Path):
        self.book = book
        self.catalog = catalog
        # The reference Tenant wrapper guards the new tenant with the
        # environment's own propose-only invariants (offer kind,
        # no self-measurement) — tenant replaceability, enforced.
        self.tenant = Tenant(AlexaTenant(catalog))
        self.receipts_dir = Path(receipts_dir)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.receipts_dir / "index.json"
        self._ids = itertools.count(1)
        self._pending: dict[str, _Pending] = {}

    # -- sealing ---------------------------------------------------------
    def _write_receipt(self, chain: ReceiptChain, run_id: str) -> str:
        path = self.receipts_dir / f"{run_id}.jsonl"
        path.write_text(chain.to_jsonl() + "\n", encoding="utf-8")
        return str(path)

    def _seal(self, chain: ReceiptChain, run_id: str, *,
              speaker_id: str, mandate_id: str | None, item: str,
              outcome: str) -> str:
        path = self._write_receipt(chain, run_id)
        rows = []
        if self.index_path.exists():
            rows = json.loads(self.index_path.read_text(encoding="utf-8"))
        rows.append({"run_id": run_id, "speaker_id": speaker_id,
                     "mandate_id": mandate_id, "item": item,
                     "outcome": outcome, "receipt": str(path)})
        self.index_path.write_text(json.dumps(rows, indent=2),
                                   encoding="utf-8")
        return str(path)

    def _result_from_run(self, run_id: str, env: Environment, result,
                         *, speaker: Speaker, hm, item: str,
                         measured_cents: int | None) -> HouseholdResult:
        path = self._seal(env.chain, run_id, speaker_id=speaker.speaker_id,
                          mandate_id=hm.mandate_id if hm else None,
                          item=item, outcome=result.outcome)
        gate = reason = None
        for v in result.verdicts:
            if v.get("status") == "refuse":
                gate, reason = v.get("gate"), v.get("reason")
        if result.outcome == "SETTLED":
            state = result.ledger_state.get(env.mandate_id, {})
            captured = state.get("captured_cents", measured_cents or 0)
            if hm is not None:
                self.book.record_settlement(hm.mandate_id, captured)
            speech = view.settled_speech(item, captured,
                                         hm.mandate.cap_cents if hm else 0)
            title = f"Ordered: {item}"
            lines = [speech, f"Receipt: {run_id}"]
        else:
            speech_reason = reason or "unmeasured"
            if speech_reason == "over_cap" and hm is not None \
                    and hm.standing and hm.spent_cents > 0:
                # The run cap was the standing budget's remainder;
                # in household language that is the cumulative cap.
                speech_reason = "over_cap_cumulative"
            speech = view.refusal_speech(
                speech_reason, item=item,
                measured_cents=measured_cents,
                cap_cents=hm.mandate.cap_cents if hm else None)
            title = f"Not ordered: {item}"
            lines = [speech, f"Gate: {gate}", f"Receipt: {run_id}"]
        return HouseholdResult(
            run_id=run_id, outcome=result.outcome, speech=speech,
            card=view.card(title, lines, result.receipt_head_hash),
            receipt_path=path, refusal_gate=gate, refusal_reason=reason,
            measured_cents=measured_cents)

    def _custody_refusal(self, speaker: Speaker, item_text: str,
                         reason: str) -> HouseholdResult:
        run_id = f"hh-run-{next(self._ids)}"
        chain = ReceiptChain()
        chain.append("run_start", {"op": "HOUSEHOLD_RUN_START",
                                   "speaker_id": speaker.speaker_id,
                                   "item": item_text})
        chain.append("gate_verdict", {"op": "GATE_VERDICT",
                                      "gate": "custody", "status": "refuse",
                                      "reason": reason, "claim_id": None})
        chain.append("run_end", {"op": "RUN_REFUSED", "gate": "custody",
                                 "reason": reason})
        path = self._seal(chain, run_id, speaker_id=speaker.speaker_id,
                          mandate_id=None, item=item_text, outcome="REFUSED")
        speech = view.refusal_speech(reason, item=item_text)
        return HouseholdResult(
            run_id=run_id, outcome="REFUSED", speech=speech,
            card=view.card(f"Not ordered: {item_text}",
                           [speech, "Gate: custody", f"Receipt: {run_id}"],
                           chain.entries[-1].hash),
            receipt_path=path, refusal_gate="custody",
            refusal_reason=reason)

    # -- phase 1: custody → propose → measure ------------------------------
    def begin(self, speaker: Speaker, item_text: str,
              listing_hint: str | None = None) -> HouseholdResult:
        hm, custody_reason = self.book.resolve(speaker, item_text)
        if hm is None:
            return self._custody_refusal(speaker, item_text, custody_reason)
        run_mandate = hm.run_mandate()
        run_id = f"hh-run-{next(self._ids)}"
        env = Environment(run_mandate, run_id=run_id,
                          mandate_id=hm.mandate_id)
        try:
            claim = self.tenant.propose(run_mandate,
                                        merchant_hint=listing_hint)
        except ProposalError:
            result = env.abort("tenant_silent")
            speech = view.refusal_speech("tenant_silent", item=item_text)
            path = self._seal(env.chain, run_id,
                              speaker_id=speaker.speaker_id,
                              mandate_id=hm.mandate_id, item=item_text,
                              outcome=result.outcome)
            return HouseholdResult(
                run_id=run_id, outcome="ABORTED", speech=speech,
                card=view.card(f"Not found: {item_text}",
                               [speech, f"Receipt: {run_id}"],
                               result.receipt_head_hash),
                receipt_path=path, refusal_reason="tenant_silent")
        measurement = self.catalog.reread(claim.subject["listing_id"])
        if measurement is None:
            # Unmeasurable: submit at once; the core gate refuses.
            # Consent is required to spend, never to refuse.
            result = env.submit_claim(claim, None)
            return self._result_from_run(run_id, env, result,
                                         speaker=speaker, hm=hm,
                                         item=item_text, measured_cents=None)
        self._pending[run_id] = _Pending(env, claim, measurement, hm,
                                         speaker, item_text)
        # The partial chain (RUN_START) is written now; confirm()
        # re-seals the same chain extended. One run, one file.
        self._write_receipt(env.chain, run_id)
        price = measurement.measured_value["price_cents"]
        speech = view.confirmation_speech(
            item_text, price, claim.asserted_value["merchant"],
            hm.mandate.cap_cents)
        return HouseholdResult(
            run_id=run_id, outcome="PENDING_CONFIRMATION", speech=speech,
            card=view.card(f"Confirm: {item_text}",
                           [speech], None),
            measured_cents=price)

    # -- phase 2: consent → gates → settle/refuse ---------------------------
    def confirm(self, run_id: str, consent: ConsentMeasurement
                ) -> HouseholdResult:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            raise ValueError(f"no pending run {run_id!r}")
        env, hm = pending.env, pending.household_mandate
        price = pending.measurement.measured_value["price_cents"]
        verdict = check_consent(env.mandate, consent, price)
        if verdict is not None:
            # The environment's public refusal path seals it: verdict
            # applied to the claim, gate_verdict on the chain,
            # RUN_REFUSED, holds released, chain verifiable.
            result = env.refuse(verdict, claim=pending.claim)
            return self._result_from_run(run_id, env, result,
                                         speaker=pending.speaker, hm=hm,
                                         item=pending.item_text,
                                         measured_cents=price)
        result = env.submit_claim(pending.claim, pending.measurement)
        if result is None:
            result = env.settle()
        return self._result_from_run(run_id, env, result,
                                     speaker=pending.speaker, hm=hm,
                                     item=pending.item_text,
                                     measured_cents=price)

    # -- replay ---------------------------------------------------------------
    def explain(self, run_id: str) -> str:
        path = self.receipts_dir / f"{run_id}.jsonl"
        return view.explain(path)
