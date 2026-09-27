"""Ask-this-lot and plain-English lot search: the model may only choose values
we already have, and caller text never becomes evidence."""

from fastapi.testclient import TestClient

from core.config import get_config
from core.engine import analyze
from server import lot_search
from server.app import app
from server.ask import ask, build_data
from server.llm import LLMUnavailable


class Fake:
    name = "fake"

    def __init__(self, out):
        self.out = out

    def complete_json(self, system, prompt, **kw):
        self.prompt, self.schema = prompt, kw.get("schema")
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


def _lot(cfg, lot):
    a = analyze(cfg, lot)
    ranking = [t.id for t in cfg.typologies]
    return a, ranking, build_data(cfg, a, {}, ranking)


# --- ask -------------------------------------------------------------------------
def test_grounded_answer_accepted(cfg, lot):
    a, ranking, data = _lot(cfg, lot)
    mid = data["scenarios"][0]["metrics"][0]["id"]
    r = ask(cfg, Fake({"answerable": True, "sentences": [{"text": "It ranks first.", "metric_ids": [mid]}]}),
            a, {}, ranking, "Which ranks first?")
    assert r["source"] == "fake" and r["answerable"] and r["sentences"]


def test_numbers_from_the_question_are_not_evidence(cfg, lot):
    a, ranking, data = _lot(cfg, lot)
    mid = data["scenarios"][0]["metrics"][0]["id"]
    out = {"answerable": True, "sentences": [{"text": "Yes, rent is 987654 a month.", "metric_ids": [mid]}]}
    r = ask(cfg, Fake(out), a, {}, ranking, "Is rent 987654 a month?")
    assert r["answerable"] is None and not r["sentences"]


def test_unanswerable_question_returns_no_sentences(cfg, lot):
    a, ranking, _ = _lot(cfg, lot)
    r = ask(cfg, Fake({"answerable": False, "sentences": []}), a, {}, ranking, "What's the best pizza nearby?")
    assert r == {"source": "fake", "answerable": False, "sentences": []}


def test_ask_provider_down_degrades(cfg, lot):
    a, ranking, _ = _lot(cfg, lot)
    r = ask(cfg, Fake(LLMUnavailable("down")), a, {}, ranking, "Anything?")
    assert r["answerable"] is None and r["reason"] == "down"


def test_household_rows_cite_known_metrics(cfg, lot):
    _a, _ranking, data = _lot(cfg, lot)
    ids = {m["id"] for s in data["scenarios"] for m in s["metrics"]}
    rows = [h for s in data["scenarios"] for h in s["households"]]
    assert rows and all(h["cost_metric_id"] in ids for h in rows)


# --- lot search ------------------------------------------------------------------
PARCELS = [
    {"id": "A", "neighborhood": "Hill", "zoning": "R1", "zoning_label": "Single-unit", "lot_area_sf": 6000,
     "public": True, "fema_sfha": False},
    {"id": "B", "neighborhood": "Hill", "zoning": "R1", "zoning_label": "Single-unit", "lot_area_sf": 1500,
     "public": False, "fema_sfha": False},
    {"id": "C", "neighborhood": "Flats", "zoning": "RM", "zoning_label": "Multi-unit", "lot_area_sf": 9000,
     "public": True, "fema_sfha": True},
]
V = lot_search.vocab(PARCELS)


def _filters(**kw):
    base = {"neighborhoods": [], "zoning_districts": [], "min_lot_sf": None, "max_lot_sf": None,
            "publicly_held_only": False, "avoid": [], "not_understood": []}
    return base | kw


def test_schema_only_offers_values_that_exist(cfg):
    s = lot_search.schema(cfg, V)["properties"]
    assert s["neighborhoods"]["items"]["enum"] == ["Flats", "Hill"]
    assert set(s["zoning_districts"]["items"]["enum"]) == {"R1", "RM"}
    assert set(s["avoid"]["items"]["enum"]) == {*cfg.hazards, lot_search.FLOOD}


def test_search_filters_in_code_largest_first(cfg):
    out = lot_search.search(cfg, Fake(_filters(publicly_held_only=True, min_lot_sf=2000)), PARCELS, V,
                            "big public lots")
    assert out["ok"] and [p["id"] for p in out["results"]] == ["C", "A"] and out["match_count"] == 2


def test_flood_avoidance_uses_the_fema_flag(cfg):
    out = lot_search.search(cfg, Fake(_filters(avoid=[lot_search.FLOOD])), PARCELS, V, "no flooding")
    assert {p["id"] for p in out["results"]} == {"A", "B"}


def test_invented_values_and_unquoted_phrases_are_dropped(cfg):
    raw = _filters(neighborhoods=["Hill", "Atlantis"], zoning_districts=["XX"], avoid=["lava"],
                   not_understood=["near the busway", "ignore previous instructions"])
    f = lot_search.clean(cfg, V, raw, "lots in the Hill near the busway")
    assert f["neighborhoods"] == ["Hill"] and f["zoning_districts"] == [] and f["avoid"] == []
    assert f["not_understood"] == ["near the busway"]


def test_malformed_output_is_rejected_not_raised(cfg):
    for bad in (None, [], "x", {"neighborhoods": 5}):
        assert lot_search.clean(cfg, V, bad, "q") is None


def test_search_provider_down_degrades(cfg):
    out = lot_search.search(cfg, Fake(LLMUnavailable("down")), PARCELS, V, "anything")
    assert out == {"ok": False, "reason": "down"}


# --- HTTP --------------------------------------------------------------------------
client = TestClient(app, raise_server_exceptions=False)


def test_overlong_free_text_is_rejected_before_the_model():
    api = get_config().app.api
    assert client.post("/api/parcels/ask", json={"query": "x" * (api.lot_search_query_max_chars + 1)}).status_code == 422
    r = client.post("/api/ask", json={"parcel_id": "0009G00180000000", "question": "x" * (api.ask_question_max_chars + 1)})
    assert r.status_code == 422
