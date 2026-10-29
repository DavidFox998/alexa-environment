# Alexa in the Environment — placement build (surface A)

Alexa as **tenant** of an Apathy-Refusal (commerce) environment,
with the Consent and Custody profiles composed. Built 2026-10-29
on David's word, from the placement design in
`goals/amazon-build-ship-shape-entry/files/ALEXA-PLACEMENT-DESIGN-2026-10-29.md`
and the contract in `TENANT-INTEGRATION-SPEC-2026-10-29.md`.

The environment core is **not forked**: this package runs on the
Environment Protocol v0 reference implementation
(`DavidFox998/soph-e-runway` — clone it alongside this repo, or
set `RUNWAY_SRC` to its `src/`) and adds the household layer
around it. The reference suite passes untouched (80/80, including
the `refuse()` API this build motivated); this package's suite
is 16/16.

## Run it

```bash
~/workspace/.zbtest-venv/bin/python -m pytest tests/ -q   # 16 tests
~/workspace/.zbtest-venv/bin/python scripts/demo.py       # narrated demo
```

## What is built

- **`tenant_alexa.py`** — Alexa as a tenant client: one method,
  `propose_offer(mandate, hint) -> Claim`, built from the
  catalog's *search* view (asserted data only). The runner wraps
  her in the reference `Tenant`, so the environment's own
  propose-only invariants (offer kind, no self-measurement) guard
  the new tenant — replaceability enforced, not asserted.
- **`catalog.py`** — listings with two views: the search card the
  tenant reads, and the record the instrument re-reads. Drift is
  real in the fixtures (search $24.10 / record $31.40; an
  off-brand record; a ghost with no record at all). In production
  surface A the record is the Amazon Pay checkout session,
  re-read through the rail built 2026-10-26; this fixture is that
  seam, labelled.
- **`household.py`** — speakers, the principal, and the mandate
  book (Custody): standing mandates with accumulating spend,
  one-shot mandates, per-speaker sub-mandates, JSON persistence.
  A run executes under the standing budget's *remainder*; the
  book keeps the original terms.
- **`consent.py`** — the Consent gate: whose voice, what was
  confirmed, at what total. The confirmation must name the
  *measured* total; consent gates settlement, never refusal (an
  unmeasurable claim is refused without asking anyone).
- **`runner.py`** — one order end to end: custody → propose →
  measure → consent → core gates → settle or named refusal →
  receipt sealed either way. Pre-gate refusals are sealed as
  verifiable chains carrying the same RUN_REFUSED shape.
- **`receipts_view.py`** — speech (refusals named in household
  language), app cards, and replay answers from the chain alone.
- **`skill.py`** — the Alexa Skills Kit envelope handler:
  OrderIntent → two-phase confirm (Yes/No) → WhyIntent replays
  the latest receipt. Transport only; all judgment is the
  environment's.

## Honest state — seams and limits

- **Settlement rail**: runs settle on the reference ledger
  (sandbox semantics, idempotent authorize/capture/release). The
  production seam is the Amazon Pay rail in zerobeacon — same
  shape, not yet wired to this package.
- **Voice identity** is a fixture boolean at one named seam
  (`skill.consent_from_session`). It is a weak instrument
  (design §5, gap 4) and is treated as one measurement, never
  as the mandate.
- **Consent refusals** are sealed through the environment's
  public refusal API (`Environment.refuse(verdict, claim)`),
  added to the reference implementation with this build: a
  composed profile's gate refuses through the same path as a
  core gate — verdict on the claim, gate_verdict on the chain,
  RUN_REFUSED, holds released.
- **Refused runs** seal no ledger hold, so a refusal's receipt
  does not carry the measured price (the reference chain shape);
  replay wording respects that rather than inventing the number.
- **Pending runs** (awaiting confirmation) hold their partial
  chain (RUN_START) on disk and complete in memory; a process
  restart mid-confirmation loses the pending run, not any money
  — nothing can settle without phase 2.
- Delivery (Gate 4 pattern over Amazon delivery photos) and the
  Alexa+ surface are designed, not built here.
