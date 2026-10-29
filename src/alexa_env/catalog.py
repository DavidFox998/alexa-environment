"""The catalog: what the tenant sees vs what the instrument re-reads.

Two views of the same listing, deliberately separate:

- `search()` is the TENANT's view: the search-result card — a price
  Alexa read off a results page, possibly stale, possibly a
  sponsored placement's price. It becomes the claim's ASSERTED
  value. The gates never consult it.
- `reread()` is the INSTRUMENT's view: the listing of record,
  re-read at gate time. It becomes the MEASUREMENT. A listing with
  no record (`record=None`) is unmeasurable: reread returns None
  and the gate refuses `unmeasured` — never a guess.

In production surface A, the record of a listing is the Amazon Pay
checkout session the environment itself created (its amount and
state re-read through the rail). The fixture stands in for that
session store; the seam is the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from runway.claims import Measurement


def norm(text: str) -> str:
    return " ".join(text.lower().split())


@dataclass
class Listing:
    listing_id: str
    item: str                       # canonical item name
    merchant: str
    search_price_cents: int         # what the tenant's search shows
    attributes: dict = field(default_factory=dict)
    currency: str = "USD"
    sponsored: bool = False
    # The listing of record. None = no instrument can read it.
    record_price_cents: int | None = None
    record_attributes: dict | None = None

    def record(self) -> dict | None:
        if self.record_price_cents is None:
            return None
        return {
            "item": self.item,
            "attributes": dict(self.record_attributes
                               if self.record_attributes is not None
                               else self.attributes),
            "price_cents": self.record_price_cents,
            "currency": self.currency,
        }


class FixtureCatalog:
    def __init__(self, listings: list[Listing]):
        self._by_id = {l.listing_id: l for l in listings}
        self._by_item: dict[str, Listing] = {}
        for l in listings:
            self._by_item.setdefault(norm(l.item), l)

    # -- tenant side --------------------------------------------------
    def search(self, item_text: str, listing_id: str | None = None
               ) -> Listing | None:
        """What Alexa finds. Returns the listing as the search page
        presents it — asserted data only. `listing_id` models the
        tenant being directed at one specific result (the top hit,
        the sponsored placement, the reorder card)."""
        if listing_id is not None:
            return self._by_id.get(listing_id)
        return self._by_item.get(norm(item_text))

    def get(self, listing_id: str) -> Listing | None:
        return self._by_id.get(listing_id)

    # -- instrument side ----------------------------------------------
    def reread(self, listing_id: str) -> Measurement | None:
        """Re-read the listing of record. None = unmeasurable."""
        listing = self._by_id.get(listing_id)
        if listing is None:
            return None
        record = listing.record()
        if record is None:
            return None
        return Measurement(
            measured_by=f"catalog-reread:{listing.listing_id}",
            measured_value=record,
            evidence_refs=[f"listing:{listing.listing_id}"],
        )


def demo_catalog() -> FixtureCatalog:
    """The demo/test universe. Drift is real: search price and record
    price differ where noted."""
    return FixtureCatalog([
        # Settles: search and record agree, under the $28 mandate cap.
        Listing("towels-12", "paper towels 12-pack", "HouseMart",
                search_price_cents=2410, record_price_cents=2410,
                attributes={"brand": "HouseMart", "pack": "12"}),
        # Drift: the search card says $24.10; the record says $31.40.
        Listing("towels-12-drift", "paper towels 12-pack",
                "HouseMart", search_price_cents=2410,
                record_price_cents=3140,
                attributes={"brand": "HouseMart", "pack": "12"}),
        # Unmeasurable: a search result with no listing of record.
        Listing("towels-12-ghost", "paper towels 12-pack",
                "UnknownSeller", search_price_cents=1999,
                record_price_cents=None,
                attributes={"brand": "HouseMart", "pack": "12"}),
        # Attribute drift: the search card shows the mandated brand;
        # the record is a different brand.
        Listing("towels-12-offbrand", "paper towels 12-pack",
                "ValueCo", search_price_cents=2200,
                record_price_cents=2200,
                attributes={"brand": "HouseMart", "pack": "12"},
                record_attributes={"brand": "ValueCo", "pack": "12"}),
    ])
