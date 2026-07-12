# 07 — Roadmap

Build the smallest thing that runs end to end, then iterate. Do not build
infrastructure ahead of data.

## Phase 0 — Design (current)

- [x] Write the project brief and architecture notes (this `docs/` folder).
- [ ] Decide the initial stack against Phase 1 (Postgres + Meilisearch/Typesense
      + Python + FastAPI is the working assumption).
- [ ] Draft the DB schema as migrations.
- [ ] Write the exclusion-blocklist policy before any harvesting runs.

## Phase 1 — Thin end-to-end slice (the MVP)

Goal: prove the whole pipeline on a narrow input.

- [ ] **One harvester.** Reddit via `praw`, polling a small set of subreddits for
      Mega/Drive links → `sighting` rows. (Reddit first — structured, documented,
      polite.)
- [ ] **Normalize/dedup** URLs → `link` rows.
- [ ] **Two enrichers.** Mega folder listing + Drive folder listing → `item`
      rows + `alive` flag. Metadata only.
- [ ] **Index** into Meilisearch/Typesense.
- [ ] **`/search` API** (FastAPI) with basic filters (provider, alive, type).
- [ ] **Validation cron** that re-checks liveness.
- [ ] **Report/takedown endpoint** + `takedown` exclusion wired through indexing.

Exit criteria: harvest → enrich → index → search works for real Reddit-sourced
links, and a reported link disappears from results.

## Phase 2 — Breadth and quality

- [ ] More sources: search-engine dorks (via a search API), Telegram, paste
      sites.
- [ ] Ranking (liveness + recency + spread + relevance) and duplicate grouping.
- [ ] Backoff-aware revalidation scheduling.
- [ ] Minimal search UI on top of the API.
- [ ] Metrics: link counts, alive ratio, source yield, enrichment error rates.

## Phase 3 — Hardening and scale

- [ ] More providers (MediaFire, Dropbox, ...).
- [ ] Robust blocklist/safety review pipeline with human-in-the-loop.
- [ ] Evaluate OpenSearch if data volume outgrows the MVP engine.
- [ ] Extract Sift into its own repository (`git subtree split --prefix=sift`).
- [ ] Operational docs: deployment, backups, ToS/quotas per source.

## Guiding priorities

1. **Safety and legality first.** Blocklists, takedowns, and metadata-only are
   not "later" — they gate Phase 1.
2. **End-to-end before wide.** One source working fully beats five half-built
   harvesters.
3. **Store is truth, index is disposable.** Never let the search index become
   something you can't rebuild.
4. **Politeness is a feature.** Rate limits and ToS respect keep the tool (and
   its operator) out of trouble.

## Open questions to resolve as we go

- Best-maintained Mega listing library vs. rolling a thin client against the
  Mega API directly?
- Drive API quota budget vs. expected enrichment volume — will the free/basic
  quota sustain Phase 1?
- Meilisearch vs. Typesense — benchmark both on a sample corpus before
  committing.
- How aggressive should default liveness re-checking be without tripping provider
  rate limits?
