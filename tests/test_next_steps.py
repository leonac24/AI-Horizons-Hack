"""Next steps per lot and the outreach drafts built on them."""

from fastapi.testclient import TestClient

from core.config import FEMA_FLOOD_FIELD
from core.engine import analyze
from core.next_steps import build, lot_fields
from server.app import app
from server.draft import build_input, draft, validate
from server.llm import LLMUnavailable


class Fake:
    name = "fake"

    def __init__(self, out):
        self.out = out

    def complete_json(self, system, prompt, **_):
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


def _steps(cfg, lot, **parcel):
    a = analyze(cfg, {**lot, **parcel})
    return a, {s.id: s for s in build(cfg, a)}


def test_private_flat_lot_only_gets_the_neighborhood_step(cfg, lot):
    _a, steps = _steps(cfg, lot, steep_slope=False, public=False)
    assert "acquire" not in steps and "site_check" not in steps
    assert "neighborhood" in steps and steps["neighborhood"].note  # RCO not joined yet: says so


def test_public_lot_routes_to_the_contact_for_its_inventory_type(cfg, lot):
    for inventory_type, contact in cfg.next_steps.acquire.by_inventory_type.items():
        _a, steps = _steps(cfg, lot, public=True, public_inventory_type=inventory_type, public_status="Available for Sale")
        assert steps["acquire"].contact == cfg.next_steps.contacts[contact]
        assert steps["acquire"].blocking and steps["acquire"].note is None
    _a, steps = _steps(cfg, lot, public=True, public_inventory_type="Something new", public_status="x")
    assert steps["acquire"].contact == cfg.next_steps.contacts[cfg.next_steps.acquire.default_contact]


def test_permanent_city_ownership_is_flagged(cfg, lot):
    status = cfg.next_steps.acquire.not_for_sale_statuses[0]
    _a, steps = _steps(cfg, lot, public=True, public_inventory_type="Park", public_status=status)
    assert status in steps["acquire"].note


def test_site_flags_each_bring_their_own_questions(cfg, lot):
    _a, steps = _steps(cfg, lot, steep_slope=True, **{FEMA_FLOOD_FIELD: True})
    qs = steps["site_check"].questions
    for q in cfg.next_steps.site_check.hazards["steep_slope"]:
        assert q in qs
    assert len(steps["site_check"].facts) == 2


def test_unmapped_district_asks_city_planning_to_confirm(cfg, lot):
    _a, steps = _steps(cfg, lot)  # conftest's TEST-D district has no rules
    assert steps["confirm"].blocking and steps["confirm"].questions


def test_template_letter_lists_every_fact_and_question(cfg, lot):
    _a, steps = _steps(cfg, lot, steep_slope=True)
    s = steps["site_check"]
    assert all(f.text in s.letter for f in s.facts) and all(q in s.letter for q in s.questions)


# --- drafts ------------------------------------------------------------------------
def _payload(cfg, lot):
    a, steps = _steps(cfg, lot, steep_slope=True)
    s = steps["site_check"]
    return a, s, build_input(s, lot_fields(a))


def test_grounded_draft_is_wrapped_in_greeting_and_sign_off(cfg, lot):
    a, s, _ = _payload(cfg, lot)
    out = {"paragraphs": [{"text": "The lot is on a steep slope.", "fact_ids": ["f1"]},
                          {"text": "Could you review it before we hire an architect?", "fact_ids": []}]}
    r = draft(cfg, Fake(out), a, s)
    d = cfg.next_steps.draft
    assert r["source"] == "fake" and r["body"].startswith(d.greeting) and r["body"].endswith(d.sign_off)


def test_draft_rejects_invented_numbers_links_and_fact_ids(cfg, lot):
    _a, _s, p = _payload(cfg, lot)
    bad = [
        {"paragraphs": [{"text": "Grading will cost 48000 dollars.", "fact_ids": ["f1"]}]},
        {"paragraphs": [{"text": "See www.example.com for the survey.", "fact_ids": ["f1"]}]},
        {"paragraphs": [{"text": "Email bob@example.com.", "fact_ids": ["f1"]}]},
        {"paragraphs": [{"text": "It is steep.", "fact_ids": ["f99"]}]},
        {"paragraphs": [{"text": "Hello there, no facts at all.", "fact_ids": []}]},
        None, {"paragraphs": "x"},
    ]
    for out in bad:
        assert validate(p, out, 5) is None, out


def test_draft_falls_back_to_the_template_letter(cfg, lot):
    a, s, _ = _payload(cfg, lot)
    r = draft(cfg, Fake(LLMUnavailable("down")), a, s)
    assert r == {"source": "template", "reason": "down", "subject": r["subject"], "to": None, "body": s.letter}


def test_draft_route_rejects_unknown_steps():
    client = TestClient(app)
    assert client.post("/api/draft", json={"parcel_id": "0011E00211000000", "step_id": "nope"}).status_code == 422
