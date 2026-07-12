# 05 — Indexing and search

Turn the enriched metadata into fast, forgiving search.

## Engine choice

Start with **Meilisearch** or **Typesense**. Both give, out of the box:

- Typo tolerance (users misspell titles and author names constantly).
- Sub-100ms queries on modest hardware.
- Faceted filtering and simple relevance tuning.
- Trivial ops (single binary / container) — right for an MVP.

Reach for **OpenSearch/Elasticsearch** only if/when scale or query complexity
outgrows the above. Don't start there; it's a lot of operational weight for a
project that has no data yet.

The search index is a **rebuildable projection** of Postgres. Postgres is the
source of truth; the index can be dropped and reconstructed at any time.

## What gets indexed

One document per `link` (see the shape in [`02-data-model.md`](./02-data-model.md)).
Key fields:

- **Searchable:** `item_names` (file/folder names inside the share) and
  `context_snippets` (the text links were posted with). These two carry almost
  all the query signal.
- **Filterable facets:** `provider`, `alive`, `top_extensions`, size ranges,
  `first_seen_at` ranges.
- **Ranking inputs:** liveness, how recently seen, how widely the link was seen
  (sighting count), and text relevance.

Documents with `takedown = true` are **never** indexed.

## Query features to aim for

- Free-text over filenames + context, typo-tolerant.
- Filters: "only alive," "only Mega," "only PDFs/epubs," "> 1 GB," "seen this
  year."
- Sort: relevance (default), most-recently-seen, largest.
- Grouping: collapse near-duplicate shares (same content re-uploaded) so results
  aren't 20 copies of one folder.

## Ranking sketch

A simple weighted score to start, tuned later:

```
score =  w1 * text_relevance
       + w2 * is_alive
       + w3 * recency(last_checked_at)
       + w4 * spread(sighting_count)
```

Alive + recently-confirmed links should beat dead ones; a link seen across many
sources is likely more significant than a one-off. Keep it explainable before
reaching for learned ranking.

## Keeping the index fresh

- On enrichment or validation change, upsert/delete the affected document.
- On `takedown`, delete the document immediately (before any slower store change).
- Support a full rebuild from Postgres for schema changes or index corruption.

## Deliberately not doing (at least at first)

- No content search (Sift has no file content — only names/metadata).
- No cross-user personalization or accounts for the MVP.
- No learned ranking until there's traffic to learn from.
