"""The Alexa Skills Kit surface: envelopes in, speech out.

The skill is a transport, nothing more: it maps an ASK request
envelope to runner calls and renders HouseholdResults as ASK
responses. All judgment lives in the environment; this module
holds only session state (which run is awaiting confirmation).

Consent construction, honestly: in phase 1 the skill speaks the
MEASURED total and asks; a YesIntent in phase 2 is treated as a
confirmation naming that item and that total, from the recognized
speaker. `speaker_recognized` stands in for the voice-profile
instrument — a weak instrument, flagged in the design (§5, gap 4);
the seam is this one function, `consent_from_session`.
"""

from __future__ import annotations

from . import receipts_view as view
from .consent import ConsentMeasurement
from .household import MandateBook
from .runner import HouseholdRunner


def _speech_response(text: str, *, card: dict | None = None,
                     end_session: bool = True,
                     session_attrs: dict | None = None) -> dict:
    response: dict = {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": end_session,
    }
    if card:
        response["card"] = {"type": "Simple", "title": card["title"],
                            "content": card["content"]}
    return {"version": "1.0",
            "sessionAttributes": session_attrs or {},
            "response": response}


def _slot(intent: dict, name: str) -> str | None:
    slot = (intent.get("slots") or {}).get(name) or {}
    return slot.get("value")


class SkillHandler:
    def __init__(self, book: MandateBook, runner: HouseholdRunner):
        self.book = book
        self.runner = runner
        self._sessions: dict[str, dict] = {}

    # -- consent seam -----------------------------------------------------
    def consent_from_session(self, session: dict, *, confirmed: bool
                             ) -> ConsentMeasurement:
        return ConsentMeasurement(
            speaker_recognized=True,    # voice-profile instrument seam
            speaker_id=session.get("speaker_id"),
            confirmed=confirmed,
            confirmed_item=session.get("pending_item"),
            confirmed_total_cents=session.get("pending_total_cents"),
        )

    # -- main entry ---------------------------------------------------------
    def handle(self, envelope: dict) -> dict:
        request = envelope.get("request") or {}
        session_id = (envelope.get("session") or {}).get("sessionId", "")
        user_id = (((envelope.get("context") or {}).get("System") or {})
                   .get("user") or {}).get("userId")
        session = self._sessions.setdefault(session_id, {})

        if request.get("type") == "LaunchRequest":
            return _speech_response(
                "This household orders under its mandates. "
                "Ask me to order something you have a mandate for.",
                end_session=False)
        if request.get("type") == "SessionEndedRequest":
            self._sessions.pop(session_id, None)
            return {"version": "1.0", "response": {}}
        if request.get("type") != "IntentRequest":
            return _speech_response("I didn't understand that.")

        intent = request.get("intent") or {}
        name = intent.get("name", "")

        if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            self._sessions.pop(session_id, None)
            return _speech_response("Stopped.")
        if name == "AMAZON.HelpIntent":
            return _speech_response(
                "Say: order, then the item in your mandate. I will "
                "verify the price before anything is charged, and I "
                "will tell you the reason if I refuse.",
                end_session=False)

        speaker = self.book.speaker_for_amazon_user(user_id) \
            if user_id else None

        if name == "OrderIntent":
            if speaker is None:
                return _speech_response(
                    "I couldn't confirm who is speaking, so I stopped.")
            item = _slot(intent, "Item")
            if not item:
                return _speech_response("What should I order?",
                                        end_session=False)
            result = self.runner.begin(
                speaker, item, listing_hint=_slot(intent, "ListingId"))
            session["speaker_id"] = speaker.speaker_id
            if result.outcome == "PENDING_CONFIRMATION":
                session["pending_run_id"] = result.run_id
                session["pending_item"] = item
                session["pending_total_cents"] = result.measured_cents
                return _speech_response(result.speech,
                                        card=result.card,
                                        end_session=False,
                                        session_attrs=session)
            return _speech_response(result.speech, card=result.card)

        if name in ("AMAZON.YesIntent", "ConfirmIntent",
                    "AMAZON.NoIntent"):
            run_id = session.get("pending_run_id")
            if not run_id:
                return _speech_response("There is nothing to confirm.")
            consent = self.consent_from_session(
                session, confirmed=(name != "AMAZON.NoIntent"))
            result = self.runner.confirm(run_id, consent)
            self._sessions.pop(session_id, None)
            return _speech_response(result.speech, card=result.card)

        if name == "WhyIntent":
            latest = view.latest_receipt(self.runner.index_path)
            if latest is None:
                return _speech_response("There are no runs to explain yet.")
            return _speech_response(view.explain(latest["receipt"]))

        return _speech_response("I didn't understand that.",
                                end_session=False)
