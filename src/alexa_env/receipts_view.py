"""Receipt views: how the household meets the record.

Three renderings of the same sealed chain:
- SPEECH — the verdict spoken, refusals with their reason named
  in household language (design §9's translation table).
- CARD — the run's receipt for the app: mandate, claim,
  measurement, verdict, head hash.
- EXPLAIN — replay: "why did we buy this / why didn't we?"
  answered from the chain alone, no tenant, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from runway.receipts import ReceiptChain


def money(cents: int | None) -> str:
    if cents is None:
        return "an unverified price"
    return f"${cents / 100:.2f}"


def refusal_speech(reason: str, *, item: str,
                   measured_cents: int | None = None,
                   cap_cents: int | None = None) -> str:
    """The named refusal, in household language (design §9)."""
    if reason == "over_cap":
        if measured_cents is None:
            # A refused run seals no ledger hold, so the measured
            # price itself is not in the chain — say so by shape,
            # never invent the number.
            return (f"The verified price was over your "
                    f"{money(cap_cents)} cap. I didn't order it.")
        return (f"That's {money(measured_cents)} delivered — over your "
                f"{money(cap_cents)} cap. I didn't order it.")
    if reason == "over_cap_cumulative":
        return ("This would put the total over the cap you set. "
                "I didn't order it.")
    if reason == "item_mismatch":
        return "That's not the item in your mandate. I didn't order it."
    if reason.startswith("attribute_mismatch:"):
        key = reason.split(":", 1)[1]
        return (f"The {key} isn't the one in your mandate. "
                f"I didn't order it.")
    if reason == "price_unmeasured":
        return "I couldn't verify the final price, so I didn't order it."
    if reason == "unmeasured":
        return "I couldn't check that independently, so I stopped."
    if reason == "currency_mismatch":
        return "That price isn't in your mandate's currency. I stopped."
    if reason == "item_absent":
        return "The delivery photo doesn't show it — I've flagged it."
    if reason.startswith("ambiguous:"):
        return "I couldn't tell from the evidence — I won't guess."
    if reason == "custody_no_mandate":
        return f"There's no mandate covering {item}, so I can't order it."
    if reason == "custody_speaker_not_authorized":
        return ("That mandate isn't scoped to you, so I can't order "
                "it on that mandate.")
    if reason == "custody_mandate_spent":
        return "That mandate's budget is fully spent for this period."
    if reason == "consent_unconfirmed":
        return "I didn't get a clear yes, so I didn't order it."
    if reason == "consent_speaker_unrecognized":
        return "I couldn't confirm that was you agreeing, so I stopped."
    if reason == "consent_item_mismatch":
        return "The confirmation named a different item, so I stopped."
    if reason == "consent_total_mismatch":
        return ("The confirmation named a different total than the "
                "verified price, so I stopped.")
    if reason == "tenant_silent":
        return (f"I couldn't find {item}, so there's nothing to "
                f"order — I didn't guess.")
    return f"I stopped: {reason}."


def settled_speech(item: str, price_cents: int, cap_cents: int) -> str:
    return (f"Ordered — {item} at {money(price_cents)} delivered, "
            f"under your {money(cap_cents)} cap.")


def confirmation_speech(item: str, price_cents: int, merchant: str,
                        cap_cents: int) -> str:
    # State the price and the cap truthfully in both directions.
    # Consent cannot override the mandate: confirming an over-cap
    # price still ends in the gate's refusal, and the speech must
    # never claim an over-cap price is under the cap.
    relation = (f"under your {money(cap_cents)} cap"
                if price_cents <= cap_cents
                else f"over your {money(cap_cents)} cap")
    return (f"The verified price for {item} is {money(price_cents)} "
            f"delivered from {merchant}, {relation}. Shall I order it?")


def card(title: str, lines: list[str], head_hash: str | None) -> dict:
    body = "\n".join(lines)
    if head_hash:
        body += f"\nReceipt head: {head_hash[:16]}…"
    return {"title": title, "content": body}


def load_chain(receipt_path: str | Path) -> ReceiptChain:
    text = Path(receipt_path).read_text(encoding="utf-8")
    chain = ReceiptChain.from_jsonl(text)
    if not chain.verify():
        raise ValueError("receipt chain does not verify; answer refused")
    return chain


def explain(receipt_path: str | Path) -> str:
    """Replay in words: reconstruct the run from its sealed receipt
    alone and say what happened and why."""
    chain = load_chain(receipt_path)
    item = None
    cap = None
    measured = None
    captured = None
    refusal = None
    aborted_reason = None
    for e in chain.entries:
        p = e.payload
        op = p.get("op")
        if e.kind == "run_start":
            if "mandate" in p:
                item = p["mandate"]["item"]
                cap = p["mandate"]["cap_cents"]
            elif "item" in p:
                item = p["item"]
        if op == "RUN_ABORTED":
            aborted_reason = p.get("reason")
        if e.kind == "claim":
            claim = p.get("claim", {})
            mv = (claim.get("measurement") or {}).get("measured_value") or {}
            if mv.get("price_cents") is not None:
                measured = mv["price_cents"]
            if item is None:
                item = (claim.get("subject") or {}).get("item")
        if op in ("LEDGER_HOLD", "LEDGER_CAPTURE") and measured is None:
            # The claim entry seals the claim as emitted (unmeasured);
            # the measured amount enters the record at the hold.
            measured = p.get("amount_cents")
        if op == "LEDGER_CAPTURE":
            captured = p.get("amount_cents", captured)
        if op == "RUN_REFUSED":
            refusal = (p.get("gate"), p.get("reason"))
        if e.kind == "gate_verdict" and p.get("status") == "refuse" \
                and refusal is None:
            refusal = (p.get("gate"), p.get("reason"))
    if refusal is not None:
        gate, reason = refusal
        return (f"Refused at the {gate} gate: {reason}. "
                + refusal_speech(reason, item=item or "it",
                                  measured_cents=measured, cap_cents=cap))
    if aborted_reason is not None:
        return (f"Run aborted: {aborted_reason}. "
                + refusal_speech(aborted_reason, item=item or "it"))
    if captured is not None:
        return (f"Bought: {item} — measured {money(measured)}, "
                f"captured {money(captured)} under a {money(cap)} cap. "
                f"The chain verifies and replays from this receipt alone.")
    return "The run ended without a settlement or a named refusal."


def latest_receipt(index_path: str | Path) -> dict | None:
    p = Path(index_path)
    if not p.exists():
        return None
    rows = json.loads(p.read_text(encoding="utf-8"))
    return rows[-1] if rows else None
