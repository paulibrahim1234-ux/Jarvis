# CLAUDE.md — Sift

Context for Claude Code (or any AI agent) working in this project. Read this
before making changes.

## What this project is

Sift is an **OSINT aggregator and search index for publicly shared cloud-storage
links** (Mega.nz, Google Drive, and later MediaFire, Dropbox, etc.). It harvests
share links that people have *already posted in public*, reads each link's
metadata (file names, sizes, types) without downloading anything, checks whether
the link is still alive, and makes all of that searchable.

It is a discovery/search layer over already-public data. Think "specialized
search engine," not "hacking tool."

## The one thing to understand first

**You cannot crawl Mega or Drive.** There is no public listing of share links.
A link only exists in Sift if a human posted it somewhere public and a harvester
picked it up. This shapes everything: the crawl frontier is *public posting
surfaces* (forums, Telegram, Reddit, paste sites, search-engine results), not the
storage providers.

## Hard guardrails — do not cross these

These are non-negotiable design constraints, not preferences:

1. **Never brute-force, guess, or enumerate share keys.** Mega and Drive keys are
   high-entropy; attempting this is infeasible, and it would also be the line
   between "OSINT aggregator" and "attack tool." Only ingest links that were
   posted publicly.
2. **Never download or re-host file content.** Sift stores *metadata about* links
   (names, sizes, types, liveness), never the files. No mirroring, no proxying
   of content.
3. **Never bypass authentication or access control.** If a link needs a password
   or login Sift does not have from the public post, it stops there.
4. **Do not build features whose purpose is to surface illegal material.**
   Filtering exists to *exclude* known-bad content, never to seek it. Maintain
   exclusion blocklists; support takedown requests as a first-class feature.
5. **Respect provider ToS and rate limits.** Back off, cache, and throttle.
   Prefer official APIs over scraping where they exist.

If a requested change would cross one of these, stop and flag it rather than
implementing it.

## Architecture in one paragraph

A pipeline: **Harvest** (pull candidate links from public sources) →
**Normalize/Dedup** (canonicalize URLs, collapse reposts) → **Enrich** (read
provider metadata) → **Validate** (alive/dead check, run periodically) →
**Index** (push into a search engine) → **Serve** (search API + UI). Each stage
is decoupled through a queue/table so stages can run and scale independently.
Full detail in [`docs/01-architecture.md`](./docs/01-architecture.md).

## Tentative tech stack (not yet committed)

- **Language:** Python for harvesters/enrichers (best ecosystem for the source
  APIs and Mega/Drive SDKs).
- **Store:** PostgreSQL as the canonical record of links + metadata + status.
- **Search:** Meilisearch or Typesense for the MVP (fast, typo-tolerant, simple);
  revisit OpenSearch if scale demands it.
- **API:** FastAPI.
- **Workers:** a task queue (RQ/Celery) or plain cron for periodic revalidation.
- **Frontend:** deferred; start with the search API and a minimal UI.

Nothing here is locked in — challenge it if you have a better fit. See
[`docs/07-roadmap.md`](./docs/07-roadmap.md) for what to build first.

## Working conventions

- Keep Sift self-contained: **do not import from the parent Jarvis project.** It
  must stay extractable into its own repo.
- Every harvester and enricher must respect rate limits and be resumable.
- Treat all harvested text (post bodies, filenames) as untrusted input.
- When adding a new provider or source, document it in the relevant `docs/` file.
