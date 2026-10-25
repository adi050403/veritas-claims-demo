# Assumptions Document — Veritas Claims

## Business assumptions

1. **Landing zone:** Clinics (or an upstream OCR/extraction service such as FASTTRACK/ARTEMIS) already deposit JSON into object storage organised as `{clinic_id}/{yyyy-mm-dd}/*.json`. Veritas does not own clinic EHR connectors in this scope.
2. **Volume:** Production targets 200k files/day with 2× burst. This prototype demonstrates correctness and architecture on the provided samples; throughput NFR is addressed by Cloud Run horizontal scale + per-file isolation rather than load-tested here.
3. **Latency tolerance for rare names:** Claims adjudication can accept ≤24h delay for unresolved test names marked `pending_ai`. All other fields stream to the warehouse immediately.
4. **PII:** Sample data is already redacted. Production would add tokenisation/masking (NFR-4.3) before analytics export — intentionally out of prototype scope.
5. **Duplicate definition:** Two files with identical canonical JSON content-hash are duplicates, even across different paths (as with Sample 1 vs Sample 3).

## Technical assumptions

1. **Dual backend:** `STORAGE_BACKEND=local` (laptop/on-prem) uses filesystem + SQLite; `gcp` uses GCS + BigQuery + Cloud Run. One codebase, env-switched.
2. **NLP tier:** spaCy is optional. Default Tier C is token Jaccard against the registry so the demo runs without large model downloads. Production may attach scispaCy/embeddings as a sidecar.
3. **Gemini:** Disabled by default (`GEMINI_ENABLED=false`). When enabled, uses `google-genai` with `temperature=0` and JSON schema. Without credentials, names remain `pending_ai` for later resolution.
4. **Schema shape:** Physical store is long/narrow (one row per lab result / medication / discharge header), aligned to the provided ideal schema CSV. A wide “5 columns per defined test” report is modelled as a BigQuery/SQLite VIEW in production; prototype UI pivots as needed.
5. **Idempotency keys:** `row_id = sha256(document_id|record_type|test_or_med|page|result|content_hash)[:32]` plus progress-file content-hash dedupe.
6. **Unit conversion:** Multiplicative factors in `units.yaml`. Ambiguous units (e.g. `%` for absolute neutrophil counts) keep original unit and rely on report-provided ranges.

## Data assumptions

1. Envelope always has `traceId`, `data.documentId`, `data.correlationId`, `data.metaDetails`, `data.responseDetails[]` with `classifier` ∈ {`lab_report`, `discharge_summary`}.
2. Lab `report_details` may contain header rows (`test_name`/`result` literals) — filtered via clinic config `skip_test_names` (ARTEMIS).
3. Age/gender/patient fields may be redacted strings; we preserve them and skip numeric age derivation when redacted.
4. Reference ranges on the report take precedence; registry ranges fill gaps.
5. Panel headers (e.g. “COMPLETE BLOOD COUNT…”) are retained as rows but often land in `pending_ai` / Invalid — acceptable; production taxonomy would mark them as non-analyte.

## Scope exclusions

| Excluded | Why | Production path |
|----------|-----|-----------------|
| Pub/Sub push trigger wiring | Assignment OK with schedule/manual run | Eventarc GCS→Pub/Sub→Cloud Run |
| Full 200k load test | Timebox | Locust/k6 + Cloud Run max-instances tuning |
| scispaCy model pack | Heavyweight for take-home | Sidecar image with model baked in |
| Real-time Cloud Monitoring alerts | Needs project IAM | Alert policies on error_rate>1%, lag>SLA |
| Wide physical table | Ideal schema is long | `CREATE VIEW report_wide AS …` |
| Full medicine formulary | Sample brand map only | External drug DB + Gemini assist |

## What we would verify before go-live

- Clinic JSON schema catalogue and versioning policy
- Authoritative LOINC/local lab code mapping (beyond string cascade)
- Legal basis for Gemini processing of residual clinical strings
- RTO/RPO for `progress.json` and registry objects
