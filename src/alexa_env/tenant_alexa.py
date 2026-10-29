"""Alexa as tenant: exactly one method wide.

Implements the tenant surface from the integration spec —
`propose_offer(mandate, merchant_hint) -> Claim` — the same
protocol Muse Spark implements in the reference tree. Alexa's
proposal is built from the catalog's SEARCH view: what a results
page showed her. That is asserted data, and it is all she gets to
say. If she finds nothing, she raises ProposalError — recorded
silence, not an invented listing.
"""

from __future__ import annotations

import itertools

from runway.claims import Claim
from runway.client import ProposalError
from runway.gates import Mandate

from .catalog import FixtureCatalog


class AlexaTenant:
    model = "alexa-skill"   # attribution identity (spec §7)

    def __init__(self, catalog: FixtureCatalog):
        self.catalog = catalog
        self._seq = itertools.count(1)

    def propose_offer(self, mandate: Mandate,
                      merchant_hint: str | None = None) -> Claim:
        # merchant_hint doubles as a listing selector: the specific
        # search result the tenant was directed at (top hit,
        # sponsored placement, reorder card).
        listing = self.catalog.search(mandate.item, listing_id=merchant_hint)
        if listing is None:
            raise ProposalError(
                f"alexa found no listing for {mandate.item!r}; silence")
        n = next(self._seq)
        return Claim(
            claim_id=f"alexa-offer-{n}",
            kind="offer",
            subject={"item": listing.item,
                     "attributes": dict(listing.attributes),
                     "listing_id": listing.listing_id},
            asserted_by=f"alexa:{self.model}",
            asserted_value={
                "price_cents": listing.search_price_cents,
                "currency": listing.currency,
                "merchant": listing.merchant,
                "sponsored": listing.sponsored,
            },
            measurement=None,
        )
