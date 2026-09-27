# Backend principles

How the Lotline API is built and why. Written to be argued with — if a rule here
costs more than it earns, change the rule and say so in the commit.

The API is **public, unauthenticated and read-only**. It serves open civic data
about parcels. That shapes almost every decision below: there is no session to
protect, so the threats worth money are *cost* (an LLM endpoint someone can bill
us on), *availability* (a cheap request that does expensive work), and
*credibility* (a number that looks authoritative and isn't).

---

## 1. The evidence boundary is a backend boundary

`core/` computes evidence. It never sees a weight. The values layer — weights,
stakeholder profiles, ranking — lives in `core/scoring.py` and its browser mirror
`web/src/lib/scoring.ts`, and the two only meet there.

This is not a style preference. It is what lets the API say "here is the number,
here is where it came from, here is how sure we are" without the answer depending
on who is asking. Any pull request that reads a weight inside `core/engine.py` or
`core/metrics.py` is wrong regardless of what it produces.

**Corollary: the client is never the source of truth.** `POST /api/explain`
accepts the caller's weights and ranking, then recomputes every metric
server-side and ignores the caller's numbers entirely. The weights are used only
to phrase the prose. A client that lies gets a correct answer anyway.

---

## 2. REST: what we follow and where we knowingly don't

We aim at the useful parts of REST — uniform resources, correct methods, correct
status codes, cacheability — not at ceremony.

| Resource | Method | Meaning |
|---|---|---|
| `/api/health` | GET | Liveness plus what this instance loaded |
| `/api/config` | GET | Labels, criteria, typologies, assumptions |
| `/api/parcels/suggested` | GET | A geographically varied starting sample |
| `/api/parcels/search?q=` | GET | Prefix match on id, substring on address |
| `/api/parcels/{id}` | GET | One parcel's index record |
| `/api/analysis/{id}` | GET | Every typology scored on that parcel |
| `/api/work-backwards/{id}` | GET | What would have to change to hit a target |
| `/api/unknowns` | GET | Placeholders, unverified sources, districts with no zoning rules |
| `/api/explain` | POST | Grounded prose over already-computed metrics |

**Status codes carry meaning.** `200` success · `304` your copy is current ·
`400` you asked for something that does not exist in config · `404` no such
parcel · `413` payload over a declared limit · `422` malformed parameter,
rejected before any work · `429` rate limited · `500` our fault, and the body
says nothing else.

**Where we deviate, deliberately:**

- **`/api/explain` is a POST that does not create anything.** It is a read whose
  input (a weight vector and a ranking) is too structured for a query string.
  It is safe and idempotent in every sense that matters — see §3. The honest
  alternative, `GET` with a long encoded query, is worse to debug and hits URL
  length limits. We took the pragmatic option and are writing it down rather
  than pretending the method is meaningful here.
- **No HATEOAS, no hypermedia.** One known client. Link relations would be
  overhead with no consumer.
- **No `/v1/` prefix yet.** There is one client, deployed together with the API.
  The first external consumer is the moment to add versioning, and the config
  hash in every response already gives us a change signal.

---

## 3. Idempotency

**Every endpoint is idempotent, including the POST.** Issue any request twice and
the second is indistinguishable from the first — no state changes, no
accumulation, no side effects. This is a property of the design, not a promise
we are asking you to trust: the API has no database and no writes.

Concretely:

- `GET /api/analysis/{id}` is a **pure function of `(parcel_id, config_hash)`**.
  The engine's uncertainty draws are seeded from `app.yaml` (`uncertainty.seed`),
  so the low/high bands are reproducible across processes and deploys. Nothing
  samples unseeded randomness. `tests/test_api.py::test_analysis_is_idempotent_and_etagged`
  pins this.
- `POST /api/explain` returns the same sentences for the same
  `(parcel, weights, ranking, config)` **when `LLM_PROVIDER=none`**, because the
  template path is deterministic. With the Anthropic provider enabled the prose may vary between
  calls — the model is not a pure function. The *grounding* is still
  deterministic: any sentence citing an unknown metric id, or a number not in the
  input, is rejected and the deterministic template is served instead. So the
  endpoint is idempotent in effect (no state) and in constraint (the same facts),
  but not byte-identical. Say this out loud rather than implying determinism we
  do not have.

**Why we do not implement `Idempotency-Key`.** That header exists to make
*non-idempotent* operations safely retryable — charge a card once despite a
timeout. We have no such operation. Adding key storage would mean adding the
first piece of mutable server state to a stateless service, to protect against a
problem we do not have. If Lotline ever writes something — a saved scenario, a
submitted review — that endpoint gets `Idempotency-Key` and a dedupe store on
day one.

**What we do instead: conditional requests.** `/api/config` and
`/api/analysis/{id}` return a strong `ETag` over the response body plus
`Cache-Control: public, max-age=<api.cache_max_age_seconds>`. A client that sends `If-None-Match` gets
`304` and no recomputation. That is the cheap, standard, correct way to make
repeated reads free.

---

## 4. Caching

Three layers, each with a stated invalidation trigger:

1. **`@lru_cache` on `get_config()` and `_index()`** — process lifetime. Config
   changes require a restart. Acceptable: config is deployed, not edited live.
2. **`@lru_cache` on `_analysis_cached(parcel_id, config_hash)`**, sized by
   `app.yaml: api.analysis_cache_entries` —
   the config hash is *in the key*, so editing any YAML in `data/config/`
   invalidates every cached analysis automatically. This is the single most
   important line in the caching story: there is no way to change an assumption
   and keep serving stale numbers.
3. **`ETag` / `304`** — pushes the cache to the client.

**Cold start.** The function reads a ~12 MB `parcels.json` on first request, then
serves from `lru_cache`. Warm requests are fast; the first one after a scale-up
is not. If cold starts become the bottleneck, the fix is to shrink the index (the
function needs a subset of the fields the map needs), not to add a cache layer.

---

## 5. Input validation

**Reject at the edge, before any work.** Every parameter that reaches a lookup or
a computation is constrained in the signature, so a malformed request costs a
422 and nothing else.

- `parcel_id` — pattern and length from `city.yaml: parcels.id_pattern`,
  `id_min_chars`, `id_max_chars`. It lives in `city.yaml` rather than
  `app.yaml` on purpose: the shape of a parcel id is a fact about the
  jurisdiction, not a tuning knob, so serving a different municipality means
  editing that block and not the route signatures. It is also what makes path
  traversal unrepresentable rather than merely handled.
- `q` — bounded by `app.yaml: api.search_query_min_chars` /
  `search_query_max_chars`. `limit` — 1..`api.search_limit_max`.
- `units` — 1..`api.work_backwards_max_units`.
  `target_ami_pct` — >0..`api.target_ami_pct_max`.
- `typology` — at most `api.id_param_max_chars`, then must exist in
  `typologies.yaml`, else `400`.
- `/api/explain` — `weights` and `ranking` are size-capped, then filtered to
  known criterion and typology ids, and weights are bounded and coerced to
  float. Unknown keys are dropped, not echoed. **Caller-supplied strings must
  never reach an LLM prompt unfiltered.**

**Limits live in `data/config/app.yaml`, not in code — and that is now
enforced.** The route signatures read the config values directly; nothing is
retyped. `tests/test_api.py::test_route_limits_are_taken_from_config_not_retyped`
asserts the published OpenAPI schema matches config field by field, so raising a
ceiling in YAML either takes effect or fails the build. It cannot silently do
nothing.

This paragraph used to claim the same thing while `units` and `target_ami_pct`
were literals in `server/app.py`, and while `q` / `limit` were declared in both
places — agreeing on the day they were written and free to drift after. The old
double bound was described as defence in depth, but it only ever worked
downwards: config could lower the ceiling and never raise it.

**Deliberately still literals**, because they are implementation details with no
policy meaning: the ETag digest length, the rate limiter's key-table bound, and
the limiter's 60-second window (that one is the *unit* of
`explain_requests_per_minute`, not an independent knob).

---

## 6. Security posture

What we actually defend against, and what we do not pretend to.

**Secrets.** `ANTHROPIC_API_KEY` is read from the environment, server-side only.
`.env` is gitignored, `.env.example` ships with empty values. No key is ever
placed in a response, a log line, or `/api/config`. The browser never holds a
model key — all LLM calls are proxied.

**Client-side data exposure — the thing to keep checking.** Everything the API
returns is public by construction, but "public data" is not the same as "safe to
publish everything we happen to have":

- **No PII, by pipeline design.** `city.yaml` whitelists the assessment fields
  that enter the pipeline. Owner names and owner mailing addresses
  (`CHANGENOTICEADDRESS*`) are never fetched. `owner_type` is a category
  (`CORPORATION`, `REGULAR`), not a person. Property addresses are public
  record. Verified against the committed `parcels.json` and the map GeoJSON.
- **`/api/config` no longer ships server filesystem paths.** `zoning.rules_file`,
  `zoning.priority_file` and `zoning.code.raw_text_dir` are stripped by
  `Config.public_json()`. Not secret, but there is no reason to hand an attacker
  our on-disk layout. Pinned by `tests/test_api.py::test_config_does_not_leak_server_paths`.
- **Error bodies say nothing.** A global exception handler logs the traceback
  server-side and returns `{"detail": "internal error"}`. Exception strings leak
  paths, config keys and library versions.
- **The static map file is the real exposure surface.** `web/public/data/parcels.geojson`
  is served by the CDN with no API in front of it. It is 5 MB of public parcel
  points and is *the* file to re-check whenever the pipeline's output columns
  change — a new field there is published to the world immediately, with no
  server-side filter to catch it.

**Headers.** `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
(keeps parcel ids out of third-party referers), `X-Frame-Options: DENY`,
`Cross-Origin-Resource-Policy: same-origin`.

**CORS is deliberately absent.** The browser app is served from the same origin.
Adding permissive CORS to a public read-only API would not leak anything, but it
would let any site drive our LLM endpoint on a visitor's IP. If a cross-origin
consumer ever appears, add an allowlist from an env var — never `*`.

**Rate limiting.** `/api/explain` is the only endpoint that costs money per call,
so it is the only one limited: fixed window, `api.explain_requests_per_minute`
per client IP. **Be honest about what this is.** It is in-process, so on a
serverless host the ceiling is per warm instance, and `X-Forwarded-For` is
client-controlled except for the hop the platform appends. It is a cost
guardrail, not an access control. A real limit needs shared state (Redis, Vercel
KV, or the platform's own WAF) and should be added before this is public for
longer than a demo.

**Prompt injection.** The model sees computed metrics and criterion labels — data
we generated — not free text from a caller. The grounding validator is the
backstop: sentences citing unknown metric ids, or numbers absent from the input,
are discarded wholesale and a template is served. The model can never change a
score; it only describes scores already computed.

**Known gaps, stated rather than hidden:** no authentication (intentional, the
data is public); no global rate limit; no request-size limit beyond the
platform's; no audit log.

---

## 7. Errors and failure

- **Degrade, never crash.** A missing parcel index logs a warning and serves an
  empty index. A missing rules file yields `needs planner review`, not a 500. An
  LLM that is down, slow, rate-limited or returns malformed JSON falls back to
  the deterministic template with a `reason` in the response body.
- **`validate()` is total.** It handles untrusted model output and returns
  `None` for anything it does not recognise — it never raises. A validator that
  can crash is a validator that can be bypassed by crashing it.
- **Unknown is a value, not an error.** Where evidence is missing the API returns
  a metric with `provenance: "placeholder"` and a note. It does not guess, and it
  does not omit the field.

---

## 8. Hard requirements vs. weighted criteria

A backend rule, because the server has to enforce it for every client.

Some things are not tradeable. A use that is **not permitted** in a district is a
hard stop; no weighting of other criteria may compensate for it. The engine marks
those scenarios `eligible: false` with a reason, and `Analysis` publishes
`rankable_typology_ids` and `excluded_typology_ids` so the browser cannot score
an ineligible scenario by accident. Excluded scenarios are still returned **in
full, with their citation** — a CDC needs to see what it cannot do and why — but
they sit outside the ranking.

Config decides which statuses are hard stops, via the `role` field in
`zoning.yaml`. Code asks for a role (`prohibited`, `unreviewed`, `variance`) and
never names a status id. Startup fails loudly if a required role is unresolvable.

---

## 9. Config over literals

Every Pittsburgh fact, tuning knob and limit lives in `data/config/*.yaml`,
validated by pydantic at import. This is enforced by tests, not by good
intentions: `tests/test_no_hardcoding.py` fails the build if a typology id,
stakeholder id, criterion id or zoning status id appears quoted in `core/`,
`server/`, `api/` or `web/src/`.

The guard covers typology, criterion, stakeholder, zoning-status **and dataset
source** ids. Source ids were the gap: `core/engine.py` carried a module
constant naming the county assessment dataset, duplicating
`city.yaml: parcels.assessments_source`, and the test never looked for it. The
engine now asks `cfg.assessment_source` — the same role-not-id pattern it already
uses for zoning statuses.

Config is validated for **cross-references**, not just shape: every stakeholder
profile must cover exactly the criteria in `criteria.yaml`; every typology's
`use_key` must exist in `zoning.yaml`; every assumption's `source` must exist in
`sources.yaml`; every zoning status must have a score; and
the two `city.yaml` keys the server depends on — the parcel id format (regex
included, it is compiled at load) and `parcels.assessments_source` — are checked
at startup even though `city` is otherwise an open section, because the running
server reads them on live requests and a typo would otherwise surface as a 500. A typo is a startup
failure with a readable message, never a silently wrong ranking.

There is exactly **one random seed** in the engine (`app.yaml:
uncertainty.seed`), reached through `Samples.stream()`. Ad-hoc
`np.random.default_rng(...)` calls are banned: they break reproducibility and
make the uncertainty bands unauditable.

---

## 10. Deployment

Static site plus one Python function. `vercel.json` builds `web/` and routes
`/api/*` to `api/index.py`, which exports the FastAPI `app` (a bare ASGI `app` is
a supported handler).

Dependencies are declared **twice on purpose**: `pyproject.toml` is the source of
truth for local `uv` development, and `requirements.txt` mirrors the runtime set
for any host that looks for it. Keep them in sync. The `pipeline` group (pandas,
GeoPandas, shapely) is excluded from both the function bundle and
`requirements.txt` — it runs offline and must never ship.

**Routing is the fragile part.** Hosts differ on whether a rewritten request
arrives at the function with its original path or the rewritten one, and a 404
from a prefix mismatch is an expensive thing to debug under time pressure. The
router is therefore mounted twice — at `/api` and at `/` — so the app answers
either way.

**Verify a deploy rather than assuming it.** Run §11 against the preview URL
before trusting it. `/api/health` returning a config hash and a non-zero parcel
count is the single check that proves the function built, the config validated,
and the data bundled.

---

## 11. Curling the endpoints

Local: `uv run uvicorn server.app:app --reload --port 8000`, then
`BASE=http://127.0.0.1:8000`. Deployed: `BASE=https://<deployment>`.

```bash
BASE=http://127.0.0.1:8000

# Did it boot, validate config, and find the parcel index?
curl -s "$BASE/api/health" | jq
# {"ok":true,"config_hash":"42360f751a2e","parcels":22183,"llm":"none"}

# Interactive schema for everything below
open "$BASE/api/docs"

# Find a parcel, then keep its id
curl -s "$BASE/api/parcels/search?q=WATERFRONT&limit=3" | jq '.[].id'
PID=$(curl -s "$BASE/api/parcels/suggested" | jq -r '.[0].id')

# Full analysis
curl -s "$BASE/api/analysis/$PID" | jq '{
  placeholders: .placeholder_count,
  rankable: .rankable_typology_ids,
  excluded: .excluded_typology_ids
}'

# One metric with its range and provenance
curl -s "$BASE/api/analysis/$PID" \
  | jq '.scenarios[0].metrics["affordability.ami_needed_pct"]'

# Anything the tool refuses to claim
curl -s "$BASE/api/unknowns" | jq '{
  placeholders: (.placeholder_assumptions | length),
  coverage: .share_covered_by_rules,
  human_checked: .share_covered_by_human_reviewed_rules
}'

# Work backwards from a target
curl -s "$BASE/api/work-backwards/$PID?typology=rowhouse&units=6&target_ami_pct=60" | jq

# Grounded explanation (POST; weights are values, recomputed evidence is ours)
curl -s -X POST "$BASE/api/explain" \
  -H 'Content-Type: application/json' \
  -d "{\"parcel_id\":\"$PID\",\"weights\":{\"affordability\":3,\"carbon\":1},\"ranking\":[]}" | jq
```

**Verifying the promises in this document:**

```bash
# Idempotent: byte-identical on repeat
diff <(curl -s "$BASE/api/analysis/$PID") <(curl -s "$BASE/api/analysis/$PID") && echo IDENTICAL

# Conditional requests: second call is 304 with no body
# Note: curl -I sends a HEAD request, and these routes only answer GET, so it
# comes back 405 with no etag header at all. Read the etag off a normal GET.
ETAG=$(curl -s -D - -o /dev/null "$BASE/api/config" | tr -d '\r' \
  | awk -F': ' 'tolower($1)=="etag"{print $2}')
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/config" -H "If-None-Match: $ETAG"   # 304

# Validation rejects before doing work
curl -s -o /dev/null -w 'bad id: %{http_code}\n'   "$BASE/api/analysis/abc!"
curl -s -o /dev/null -w 'big limit: %{http_code}\n' "$BASE/api/parcels/search?q=00&limit=99999"

# Security headers present
curl -s -D - -o /dev/null "$BASE/api/health" | grep -iE 'x-content-type-options|referrer-policy'

# No server paths in the browser payload (expect no output)
curl -s "$BASE/api/config" | jq '.zoning | keys' | grep -E 'rules_file|priority_file'

# Rate limit trips (expect 200s then 429s)
for i in $(seq 1 15); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/api/explain" \
    -H 'Content-Type: application/json' \
    -d "{\"parcel_id\":\"$PID\",\"weights\":{},\"ranking\":[]}"
done; echo
```

---

## 12. Testing

`uv run pytest` — 50 tests, no network, no LLM calls.

What each group is actually protecting:

- **Config** — cross-reference validation and loud failure on bad config.
- **Scoring** — direction-aware normalization, SMAA indices summing to 1,
  ranking flip on a toy example.
- **Zoning** — rule evaluation; with `require_human_review` on, unreviewed means
  unreviewed; with it off, extracted rules answer but report `human_reviewed: false`.
- **Eligibility** — a prohibited use is excluded from the ranking, a rule not in
  force excludes nothing, and an unresolvable status role fails at startup.
- **No-hardcoding** — fake typologies work end to end; no config-declared id is
  quoted in code.
- **Coverage** — random real parcels across the city all return complete
  responses.
- **API** — limits, 304s, header presence, path-leak prevention, idempotence,
  and that every route bound is the config value rather than a copy of it.
- **Explanation grounding** — ungrounded model output is rejected.

**The test that matters most is the no-hardcoding one.** It is the only thing
standing between this codebase and a hundred small Pittsburgh literals creeping
back into `core/`. It has already caught two real regressions in this branch.
