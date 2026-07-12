# 02 — Data model

A sketch of the canonical schema. Names are illustrative; refine when
implementing. The guiding principle: **the store holds metadata and provenance,
never file content.**

## Core tables

### `source`
A public place links are harvested from.

| column | type | notes |
| --- | --- | --- |
| `id` | pk | |
| `kind` | enum | `reddit`, `telegram`, `paste`, `forum`, `search_dork`, ... |
| `identifier` | text | e.g. subreddit name, channel id, base URL |
| `cursor` | jsonb | resume state for the harvester |
| `enabled` | bool | |
| `last_harvested_at` | timestamptz | |

### `sighting`
One observation of a link in the wild. Many sightings can map to one link.

| column | type | notes |
| --- | --- | --- |
| `id` | pk | |
| `source_id` | fk → source | |
| `raw_url` | text | exactly as found |
| `context_text` | text | post title/body around the link — **key search signal** |
| `posted_at` | timestamptz | when the post was made, if known |
| `seen_at` | timestamptz | when Sift harvested it |
| `link_id` | fk → link | set during normalize/dedup |

### `link`
The canonical, deduplicated share.

| column | type | notes |
| --- | --- | --- |
| `id` | pk | |
| `provider` | enum | `mega`, `gdrive`, `mediafire`, ... |
| `canonical_url` | text unique | normalized form |
| `external_id` | text | folder/file id extracted from URL |
| `is_folder` | bool | |
| `first_seen_at` | timestamptz | earliest sighting |
| `alive` | bool nullable | null = never validated |
| `last_checked_at` | timestamptz | |
| `check_backoff` | interval | how long until next validation |
| `takedown` | bool | if true, excluded from index/serving |

> Note on keys: for Mega, the decryption key lives in the URL fragment and is
> required to read metadata. Treat the full `canonical_url` (including fragment)
> as the record, but be deliberate about where it is logged. It came from a
> public post, but Sift should not casually spray it into logs.

### `item`
A file or folder discovered *inside* a link during enrichment. This is the
searchable payload. No content — just metadata.

| column | type | notes |
| --- | --- | --- |
| `id` | pk | |
| `link_id` | fk → link | |
| `path` | text | relative path within the share |
| `name` | text | file/folder name — **primary search field** |
| `is_dir` | bool | |
| `size_bytes` | bigint nullable | |
| `mime_or_ext` | text | best-effort type |
| `enriched_at` | timestamptz | |

### `report`
Takedown / removal requests. First-class, not bolted on.

| column | type | notes |
| --- | --- | --- |
| `id` | pk | |
| `link_id` | fk → link | |
| `reason` | enum | `dmca`, `illegal`, `privacy`, `owner_request`, ... |
| `details` | text | |
| `status` | enum | `open`, `actioned`, `rejected` |
| `created_at` | timestamptz | |

## The search document

The index gets a denormalized projection per link, roughly:

```json
{
  "link_id": "...",
  "provider": "mega",
  "canonical_url": "...",
  "is_folder": true,
  "alive": true,
  "first_seen_at": "2026-01-04T...",
  "last_checked_at": "2026-07-10T...",
  "context_snippets": ["posted title / body text from sightings"],
  "item_count": 412,
  "total_size_bytes": 88123456789,
  "item_names": ["Anatomy - Gray's.pdf", "Lecture 03.mp4", "..."],
  "top_extensions": ["pdf", "mp4", "epub"]
}
```

Searchable fields: `item_names`, `context_snippets`. Facets/filters: `provider`,
`alive`, `top_extensions`, `total_size_bytes` (ranges), `first_seen_at` (ranges).
Excluded from the index entirely when `takedown = true`.

## Provenance, not just latest state

Keeping every `sighting` (rather than overwriting) means Sift can answer "where
did this circulate and when," dedupe reposts, and rank by how widely a link
spread — all without re-harvesting.
