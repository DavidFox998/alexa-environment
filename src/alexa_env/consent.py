"""The Consent gate: did the principal actually agree — to this?

A spoken "yes" in a living room is a claim about consent, and it
is measured like any other claim: WHOSE voice, WHAT was confirmed,
AT WHAT TOTAL. The confirmation the skill collects must name the
measured item and the measured total — a yes to a price the
instrument never read is not consent to the charge that follows.

Returns a Verdict on refusal, None on pass (profile-gate shape:
the runner seals refusals through the environment's own refusal
path, so a consent refusal leaves the same receipt as a gate
refusal).
"""

from __future__ import annotations

from dataclasses import dataclass

from runway.gates import Mandate, Verdict


@dataclass
class ConsentMeasurement:
    speaker_recognized: bool        # voice matched an enrolled speaker
    speaker_id: str | None          # who the instrument says spoke
    confirmed: bool                 # an explicit yes was captured
    confirmed_item: str | None      # the item as spoken back
    confirmed_total_cents: int | None  # the total as spoken back


def check_consent(mandate: Mandate, consent: ConsentMeasurement,
                  measured_total_cents: int) -> Verdict | None:
    gate = "consent"
    if not consent.confirmed:
        return Verdict("refuse", gate, "consent_unconfirmed")
    if not consent.speaker_recognized or consent.speaker_id is None:
        return Verdict("refuse", gate, "consent_speaker_unrecognized")
    if consent.confirmed_item is not None and \
            consent.confirmed_item.strip().lower() != mandate.item.strip().lower():
        return Verdict("refuse", gate, "consent_item_mismatch")
    if consent.confirmed_total_cents is not None and \
            consent.confirmed_total_cents != measured_total_cents:
        return Verdict("refuse", gate, "consent_total_mismatch")
    return None
