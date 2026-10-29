"""The household: speakers, principals, and the mandate book.

Custody lives here. The PRINCIPAL is the account holder — the
person whose payment instrument and name are on the account.
Other household members are SPEAKERS: they may invoke only the
mandates the principal scoped to them (sub-mandates). A claim can
be true, measured, and in-cap, and still refuse here, because it
was spoken under the wrong mandate.

A mandate is the reference `runway.gates.Mandate`, unchanged —
item, exact attributes, positive cap, currency, deadline — plus
household bookkeeping: who issued it, who may invoke it, whether
it is standing (renews; spend accumulates against the cap) or
one-shot, and how much a standing mandate has already settled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from runway.gates import Mandate

from .catalog import norm


@dataclass
class Speaker:
    speaker_id: str
    name: str
    is_principal: bool = False
    amazon_user_id: str | None = None   # skill-envelope user mapping


@dataclass
class HouseholdMandate:
    mandate_id: str
    principal_id: str                   # who issued it (a speaker_id)
    mandate: Mandate                    # the exact terms (runway type)
    speaker_ids: list[str]              # who may invoke it
    standing: bool = False              # standing = cap is a period budget
    spent_cents: int = 0                # settled so far (standing only)
    active: bool = True

    def run_mandate(self) -> Mandate:
        """The mandate a single run executes under. For a standing
        mandate the run's cap is what remains of the period budget;
        the book keeps the original terms and the spend."""
        if not self.standing:
            return self.mandate
        remaining = self.mandate.cap_cents - self.spent_cents
        return Mandate(
            item=self.mandate.item,
            attributes=dict(self.mandate.attributes),
            cap_cents=max(remaining, 0) if remaining > 0 else 0,
            currency=self.mandate.currency,
            deadline_iso=self.mandate.deadline_iso,
        )


@dataclass
class MandateBook:
    speakers: dict[str, Speaker] = field(default_factory=dict)
    mandates: dict[str, HouseholdMandate] = field(default_factory=dict)

    # -- people ---------------------------------------------------------
    def add_speaker(self, speaker: Speaker) -> None:
        self.speakers[speaker.speaker_id] = speaker

    def speaker_for_amazon_user(self, amazon_user_id: str) -> Speaker | None:
        for s in self.speakers.values():
            if s.amazon_user_id == amazon_user_id:
                return s
        return None

    # -- mandates -------------------------------------------------------
    def issue(self, hm: HouseholdMandate) -> None:
        issuer = self.speakers.get(hm.principal_id)
        if issuer is None or not issuer.is_principal:
            raise ValueError("only the principal issues mandates")
        self.mandates[hm.mandate_id] = hm

    def resolve(self, speaker: Speaker, item_text: str
                ) -> tuple[HouseholdMandate | None, str | None]:
        """Custody resolution: which mandate, if any, governs this
        speaker asking for this item.

        Returns (mandate, None) or (None, named_refusal_reason):
        - custody_no_mandate: nothing covers this item at all.
        - custody_speaker_not_authorized: a mandate covers the item
          but this speaker is not in its scope.
        - custody_mandate_spent: a standing mandate's budget is gone.
        """
        wanted = norm(item_text)
        covering = [m for m in self.mandates.values()
                    if m.active and norm(m.mandate.item) == wanted]
        if not covering:
            return None, "custody_no_mandate"
        for m in covering:
            if speaker.speaker_id in m.speaker_ids:
                if m.standing and m.spent_cents >= m.mandate.cap_cents:
                    return None, "custody_mandate_spent"
                return m, None
        return None, "custody_speaker_not_authorized"

    def record_settlement(self, mandate_id: str, captured_cents: int) -> None:
        m = self.mandates[mandate_id]
        if m.standing:
            m.spent_cents += captured_cents

    # -- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "speakers": {sid: vars(s) for sid, s in self.speakers.items()},
            "mandates": {
                mid: {
                    "mandate_id": m.mandate_id,
                    "principal_id": m.principal_id,
                    "speaker_ids": list(m.speaker_ids),
                    "standing": m.standing,
                    "spent_cents": m.spent_cents,
                    "active": m.active,
                    "mandate": {
                        "item": m.mandate.item,
                        "attributes": dict(m.mandate.attributes),
                        "cap_cents": m.mandate.cap_cents,
                        "currency": m.mandate.currency,
                        "deadline_iso": m.mandate.deadline_iso,
                    },
                } for mid, m in self.mandates.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MandateBook":
        book = cls()
        for sid, s in d.get("speakers", {}).items():
            book.speakers[sid] = Speaker(**s)
        for mid, m in d.get("mandates", {}).items():
            md = m.pop("mandate")
            book.mandates[mid] = HouseholdMandate(
                mandate=Mandate(**md), **m)
        return book

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MandateBook":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def demo_book() -> MandateBook:
    """The demo household: Dana (principal), Sam (partner, scoped to
    the towels mandate), Kit (child, snack sub-mandate only)."""
    book = MandateBook()
    book.add_speaker(Speaker("dana", "Dana", is_principal=True,
                             amazon_user_id="amzn-user-dana"))
    book.add_speaker(Speaker("sam", "Sam", amazon_user_id="amzn-user-sam"))
    book.add_speaker(Speaker("kit", "Kit", amazon_user_id="amzn-user-kit"))
    book.issue(HouseholdMandate(
        mandate_id="towels-standing",
        principal_id="dana",
        mandate=Mandate(item="paper towels 12-pack",
                        attributes={"brand": "HouseMart", "pack": "12"},
                        cap_cents=2800, currency="USD"),
        speaker_ids=["dana", "sam"],
        standing=True,
    ))
    book.issue(HouseholdMandate(
        mandate_id="kit-snacks",
        principal_id="dana",
        mandate=Mandate(item="fruit snacks",
                        attributes={}, cap_cents=1500, currency="USD"),
        speaker_ids=["kit"],
        standing=False,
    ))
    return book
