"""Narrated end-to-end demo: Alexa inside the environment.

Run:  ~/workspace/.zbtest-venv/bin/python scripts/demo.py
Every scenario prints what the household hears, and every receipt
is verified + replayed before the demo moves on.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "conftest.py").replace(
    "/conftest.py", ""))
import conftest  # noqa: F401  (installs sys.path for src + runway)

from alexa_env import receipts_view as view
from alexa_env.catalog import demo_catalog
from alexa_env.consent import ConsentMeasurement
from alexa_env.household import demo_book
from alexa_env.runner import HouseholdRunner

RUNS = Path(__file__).parent.parent / "runs-demo"
shutil.rmtree(RUNS, ignore_errors=True)

book = demo_book()
runner = HouseholdRunner(book, demo_catalog(), RUNS)
dana = book.speakers["dana"]
kit = book.speakers["kit"]


def consent(speaker_id, item, total, confirmed=True, recognized=True):
    return ConsentMeasurement(recognized, speaker_id, confirmed, item, total)


def show(title, result):
    print(f"\n== {title}")
    print(f"   outcome: {result.outcome}")
    print(f"   Alexa:   {result.speech}")
    if result.receipt_path:
        chain = view.load_chain(result.receipt_path)
        print(f"   receipt: {result.receipt_path} "
              f"(chain verifies: {chain.verify()})")
        print(f"   replay:  {view.explain(result.receipt_path)}")


# 1. The clean settle: measured price spoken, consent, capture.
r = runner.begin(dana, "paper towels 12-pack")
print(f"\n== 1. Dana orders towels — confirmation")
print(f"   Alexa:   {r.speech}")
r = runner.confirm(r.run_id, consent("dana", "paper towels 12-pack", 2410))
show("1b. Dana confirms", r)

# 2. Drift: the search card said $24.10; the record says $31.40.
#    Dana confirms the real total anyway — consent cannot override
#    the mandate, and the gate still refuses. (The run's cap here is
#    the standing budget's remainder: $28.00 - $24.10 spent = $3.90.)
r = runner.begin(dana, "paper towels 12-pack",
                 listing_hint="towels-12-drift")
print(f"\n== 2. The sponsored result drifted — confirmation cites "
      f"the MEASURED price")
print(f"   Alexa:   {r.speech}")
r = runner.confirm(r.run_id, consent("dana", "paper towels 12-pack", 3140))
show("2b. Dana confirms the real total; the gate still refuses", r)

# 3. Custody: Kit (child) reaches for the household towels mandate.
r = runner.begin(kit, "paper towels 12-pack")
show("3. Kit tries the towels mandate", r)

# 4. Unmeasured: a listing with no record. Refused without consent —
#    consent gates settlement, never refusal.
r = runner.begin(dana, "paper towels 12-pack",
                 listing_hint="towels-12-ghost")
show("4. The ghost listing", r)

# 5. Consent: Dana confirms a different total than measured.
r = runner.begin(dana, "paper towels 12-pack")
r = runner.confirm(r.run_id, consent("dana", "paper towels 12-pack", 2000))
show("5. Confirmation names the wrong total", r)

print(f"\nStanding mandate spend after the demo: "
      f"${book.mandates['towels-standing'].spent_cents / 100:.2f} "
      f"of $28.00 (only scenario 1 settled)")
