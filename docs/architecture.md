# Veritas Claims — Solution Architecture

**Pattern:** stream-first, resolve-async · **Target:** GCS + Cloud Run + BigQuery (+ Vertex Gemini) · **Laptop fallback:** local folder + SQLite + Streamlit

See also: [architecture.png](architecture.png) / [veritas-claims-architecture.drawio](veritas-claims-architecture.drawio)

## 1. How functional requirements are met

| FR | Approach |
|----|----------|
| FR-1 Ingestion | Object store abstraction lists `{clinic_id}/{yyyy-mm-dd}/*.json`. Envelope validation + content-hash dedupe. Malformed files → quarantine + dead-letter. |
| FR-2 Standardisation | Config-driven clinic YAML maps field paths. Test-name cascade (exact → fuzzy → NLP → Gemini). Numeric/unit/date/gender/medicine helpers. |
| FR-3 Validation | Range + physiological outlier bounds → `test_analytics` ∈ {Within Range, Above Range, Below Range, Outlier, Invalid}. |
| FR-4 Storage | Long/narrow canonical table (SQLite local / BigQuery cloud). Idempotent upsert on `row_id`. Raw lineage via `file_gcs_path` + `content_hash`. |
| FR-5 Ops UI | Streamlit dashboard: run stats, flagged queue, clinic quality, raw+standardised inspector. |

## 2. Pipeline stages (Cloud Run service, min instances = 0)

1. **Ingest** — discover, parse, envelope check, dedupe, checkpoint `state/progress.json`
2. **Map** — clinic YAML field paths → intermediate rows (lab_result / discharge_summary / medication)
3. **Standardise** — cascade + parsers; unresolved names get `pending_ai=true`
4. **Validate** — ranges / outliers / invalid flags
5. **Stream Load** — MERGE/UPSERT immediately (does **not** wait for Gemini)

## 3. Test-name resolution cascade (cost-ordered)

```
A Exact/registry (+ learned Gemini aliases)  → free
B rapidfuzz WRatio                           → cheap CPU
C token Jaccard (+ optional spaCy)           → local mid-cost
D Gemini Flash async worker ≤24h SLA         → last resort
```

Resolved aliases are **written back** to `config/registry/test_names.yaml` (`learned_aliases`) so spend shrinks over time.

## 4. NFR notes

- **Scale:** Cloud Run horizontal scale; object-store list + per-file isolation. Local mode processes sample volume for the assignment.
- **Zero-code onboarding:** add `config/clinics/{SOURCE}.yaml` + registry aliases — no code change.
- **Reliability:** one file failure does not block others; progress checkpoints enable crash/OOM resume; content-hash + `row_id` give idempotency.
- **Lineage:** every row carries `document_id`, `correlation_id`, `file_gcs_path`, `content_hash`, timestamps.
- **Observability:** JSON structured logs with correlation fields; progress summary + UI metrics; alert hooks described in assumptions (Cloud Monitoring in prod).

## 5. Cost levers

- GCS for all JSON (cheap durable landing zone)
- Cloud Run scale-to-zero
- Gemini only for unresolved names; registry feedback loop reduces future AI calls

## 6. Trade-offs

| Choice | Why | Trade-off |
|--------|-----|-----------|
| Long/narrow table + optional wide VIEW | Matches assignment ideal schema; easier MERGE | Wide “5 cols per test” is a VIEW, not physical |
| Async AI | Keeps p95 latency under SLA for majority | Rare names lag ≤24h |
| Config YAML over code | Clinic onboarding without deploys | Complex nested JSON still needs path design |
| SQLite local / BQ cloud | Same code path via `RecordStore` | Local ≠ production concurrency |
