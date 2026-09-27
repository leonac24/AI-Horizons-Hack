"""Grounded explanations. The model sees only computed metrics + current weights.
Every sentence must cite metric ids from the input and may only use numbers that
appear in the input; otherwise we fall back to a deterministic template."""

from __future__ import annotations

import json
import logging
import re

from core.config import Config
from core.engine import Analysis
from server.llm import LLMUnavailable, Provider

SYSTEM = """You explain tradeoffs between housing options for one vacant lot in Pittsburgh.
Rules:
- Use ONLY the facts in the input JSON. Do not add outside facts.
- Write at most {max_sentences} sentences.
- Every sentence must list the metric ids it relies on in "metric_ids" (ids exactly as given).
  A sentence that cites no metric is rejected, so do not open with lot context
  (neighborhood, zoning, lot size) on its own; start with the tradeoffs.
- Only use numbers that appear in the input (you may round them).
- Describe tradeoffs and how the ranking depends on the weights. Never say what should be built.
- If a metric's provenance is "placeholder", say the value is a placeholder.
Return JSON: {"sentences": [{"text": "...", "metric_ids": ["..."]}]}"""

# Enforced by the API; the grounding checks in validate() still run on top.
# minItems 0/1 is the only array bound structured outputs accept, so the
# sentence cap lives in the prompt and validate() truncates to it.
SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "metric_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                },
                "required": ["text", "metric_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sentences"],
    "additionalProperties": False,
}

log = logging.getLogger("lotline.explain")

NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def build_input(cfg: Config, a: Analysis, weights: dict[str, float], ranking: list[str]) -> dict:
    crit = {c.metric_id: c for c in cfg.criteria}
    labels = {t.id: t.label for t in cfg.typologies}
    top = ranking[:3] if ranking else [s.typology_id for s in a.scenarios[:3]]
    scen = {s.typology_id: s for s in a.scenarios}
    return {
        "lot": {"neighborhood": a.parcel.get("neighborhood"), "zoning_district": a.parcel.get("zoning"),
                "lot_area_sf": a.parcel.get("lot_area_sf")},
        "weights": {c.label: round(weights.get(c.id, 0), 2) for c in cfg.criteria},
        "ranking_under_current_weights": [labels[t] for t in top],
        "scenarios": [
            {"housing_type": labels[t], "homes": scen[t].units,
             "metrics": [{"id": f"{t}:{mid}", "label": m.label, "value": m.value, "low": m.low, "high": m.high,
                          "unit": m.unit, "provenance": m.provenance,
                          "direction": crit[mid].direction if mid in crit else None}
                         for mid, m in scen[t].metrics.items() if mid in crit]}
            for t in top if t in scen
        ],
    }


def _allowed_numbers(payload: dict) -> set[float]:
    nums: set[float] = set()
    for tok in NUM.findall(json.dumps(payload)):
        try:
            x = float(tok.replace(",", ""))
        except ValueError:
            continue
        nums |= {x, round(x), round(x, 1), round(x, 2), round(x * 100) / 100}
        if 0 < abs(x) <= 1:
            nums.add(round(x * 100))  # 0.45 -> "45%"
    return nums


def validate(payload: dict, out: object, max_sentences: int) -> list[dict] | None:
    """Return grounded sentences, or None if anything at all is off.

    Everything here is untrusted model output, so the function is total: any
    shape it does not recognise is a rejection, never an exception. A validator
    that can raise is a validator that can be bypassed by crashing it.
    """
    if not isinstance(out, dict):
        return None
    ids = {m["id"] for s in payload["scenarios"] for m in s["metrics"]}
    allowed = _allowed_numbers(payload)
    sentences = out.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        return None
    clean = []
    for s in sentences[:max_sentences]:
        if not isinstance(s, dict):
            return None
        text, mids = s.get("text"), s.get("metric_ids")
        if not isinstance(text, str) or not text.strip() or not isinstance(mids, list) or not mids:
            return None
        if any(not isinstance(m, str) or m not in ids for m in mids):
            return None
        for tok in NUM.findall(text):
            try:
                x = float(tok.replace(",", "").rstrip("."))
            except ValueError:
                return None
            if x not in allowed and round(x) not in allowed:
                return None
        clean.append({"text": text, "metric_ids": mids})
    return clean


def template(cfg: Config, payload: dict) -> list[dict]:
    out: list[dict] = []
    labels = {c.metric_id: c for c in cfg.criteria}
    scen = payload["scenarios"]
    if not scen:
        return out
    first = scen[0]
    out.append({"text": f"Under the current weights, {first['housing_type']} ranks first here "
                        f"with {first['homes']} homes.", "metric_ids": [first["metrics"][0]["id"]]})
    if len(scen) > 1:
        second = scen[1]
        for m1, m2 in zip(first["metrics"], second["metrics"]):
            better = (m1["value"] > m2["value"]) == (m1["direction"] == "higher_is_better")
            if m1["value"] != m2["value"]:
                crit = labels[m1["id"].split(":", 1)[1]]
                who, other = (first, second) if better else (second, first)
                out.append({"text": f"On '{crit.label.lower()}', {who['housing_type']} does better than "
                                    f"{other['housing_type']}.", "metric_ids": [m1["id"], m2["id"]]})
            if len(out) >= 4:
                break
    placeholders = [m["id"] for s in scen for m in s["metrics"] if m["provenance"] == "placeholder"]
    if placeholders:
        out.append({"text": "Several of these values are placeholders, so treat the ranking as a "
                            "demonstration of the tradeoffs rather than a finding.", "metric_ids": placeholders[:3]})
    return out


def explain(cfg: Config, provider: Provider, a: Analysis, weights: dict[str, float], ranking: list[str]) -> dict:
    payload = build_input(cfg, a, weights, ranking)
    try:
        s = cfg.app.explanation
        system = SYSTEM.replace("{max_sentences}", str(s.max_sentences))
        out = provider.complete_json(system, json.dumps(payload), schema=SCHEMA, effort=s.effort,
                                     timeout_s=s.timeout_s, max_tokens=s.max_tokens)
        sentences = validate(payload, out, s.max_sentences)
        if sentences:
            return {"source": provider.name, "sentences": sentences}
        reason = "model output failed grounding checks"
    except LLMUnavailable as e:
        reason = str(e)
    except Exception:
        # The explanation is decoration over a ranking the client already has.
        # Nothing the provider can do should turn this endpoint into a 500.
        log.exception("explanation provider raised; falling back to template")
        reason = "explanation provider error"
    return {"source": "template", "reason": reason, "sentences": template(cfg, payload)}
