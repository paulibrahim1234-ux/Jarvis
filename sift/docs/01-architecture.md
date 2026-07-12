# 01 — Architecture

## The pipeline

Sift is a linear pipeline with a durable store between each stage, so stages run
independently, can be retried, and can scale at different rates.

```
                        ┌─────────────────────────────────────────────┐
                        │                 canonical store              │
                        │            (PostgreSQL: links, metadata,      │
                        │             sources, status, history)         │
                        └───────▲───────────▲───────────▲──────────────┘
                                │           │           │
   public sources        ┌─────┴─────┐ ┌───┴────┐ ┌────┴─────┐      ┌──────────┐
  (forums, TG, reddit,   │  HARVEST  │ │ ENRICH │ │ VALIDATE │      │  INDEX   │
   paste, dorks) ───────▶│  extract  │▶│ read   │▶│ alive?   │─────▶│  push to │
                         │  links    │ │ meta   │ │ (cron)   │      │  search  │
                         └───────────┘ └────────┘ └──────────┘      └────┬─────┘
                                                                          │
                                                                    ┌─────▼─────┐
                                                                    │   SERVE   │
                                                                    │ API + UI  │
                                                                    └───────────┘
```

## Stages

### 1. Harvest
Pull candidate links from public posting surfaces. One harvester per source type
(Reddit, Telegram, a paste site, search-engine dorks, ...). A harvester's only
job is: read public posts, extract share-link URLs plus the surrounding context
text, and write raw `sighting` rows. Harvesters must be **resumable** (track a
cursor per source) and **polite** (respect rate limits / robots / API ToS).

See [`03-link-discovery.md`](./03-link-discovery.md).

### 2. Normalize & dedup
Canonicalize each URL (a single Mega folder can be written many ways; strip
tracking params; standardize the fragment). Collapse many sightings of the same
underlying share into one `link` row, keeping every sighting as provenance
("first seen here, also seen there"). This is plain code, not a service.

### 3. Enrich
For each new/changed link, call the provider to read metadata **without
downloading**: folder tree, file names, sizes, MIME/type guesses, item counts.
Store it. This is where a link becomes searchable.

See [`04-metadata-extraction.md`](./04-metadata-extraction.md).

### 4. Validate
Links rot. A scheduled job re-checks liveness (folder still resolves? file still
present?) and flips an `alive` flag with a `last_checked` timestamp. Frequency
backs off for stably-alive links and stably-dead ones.

### 5. Index
Push the canonical record + enriched metadata into the search engine as
documents optimized for query. The store remains the source of truth; the index
is a rebuildable projection.

See [`05-indexing-and-search.md`](./05-indexing-and-search.md).

### 6. Serve
A `/search` API over the index (query + facets: provider, type, size, alive,
date), plus a minimal UI. Also hosts the takedown/report endpoint.

## Why a store between every stage

- **Decoupling:** the enricher can be down for an hour without losing harvested
  links; validation runs on its own cadence.
- **Retry & backfill:** re-run enrichment for a provider after fixing a bug
  without re-harvesting.
- **Provenance:** keep the full history of where/when each link was seen.
- **Rebuildable index:** the search index is disposable; Postgres is truth.

## Tech choices (tentative)

| Concern | Choice | Why |
| --- | --- | --- |
| Harvesters / enrichers | **Python** | Best ecosystem: `praw` (Reddit), `telethon` (Telegram), Mega SDKs, Google API client |
| Canonical store | **PostgreSQL** | Relational provenance, JSONB for flexible metadata, mature |
| Search | **Meilisearch** or **Typesense** | Fast, typo-tolerant, trivial to run for an MVP; swap to OpenSearch only if scale forces it |
| API | **FastAPI** | Async, typed, quick to stand up |
| Workers / schedule | **RQ** or **Celery**, or plain **cron** to start | Periodic validation + async enrichment |
| Frontend | deferred | Ship the API first; a thin search page later |

None of this is committed. The roadmap starts with the smallest thing that runs
end to end, and stack decisions get made against that.

## Deployment shape (later)

Single small VM or container stack to start: Postgres + Meilisearch + one API
process + one worker on a cron. Nothing here needs to be distributed until the
link count is large. Do not over-build the infrastructure before there is data
flowing through the pipeline.
