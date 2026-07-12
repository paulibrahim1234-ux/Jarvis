# 00 — Overview

## The problem, stated plainly

People share large collections of files through cloud lockers — Mega.nz folders,
Google Drive folders, MediaFire, etc. Textbooks, course archives, media,
datasets. These links circulate in public (forums, chat channels, social posts),
get useful for a while, and periodically disappear (takedowns, expiry, account
bans).

There is no search box for this. If you did not catch the post where a link was
shared, you generally cannot find it again, and you cannot ask "what public
shares exist that contain X." Sift is an attempt to build that missing search box
— for research and situational awareness about what is publicly reachable.

## Why you cannot just "crawl Mega/Drive"

This is the load-bearing fact of the whole project.

- **No directory exists.** Neither Mega nor Google publishes a list of shared
  links. That is a deliberate privacy property of the services.
- **Links are unguessable.** A Mega link embeds a high-entropy decryption key in
  the URL fragment (`#F!<id>!<key>`). Google Drive folder IDs are long random
  strings. You cannot enumerate the space; brute force is both computationally
  hopeless and off-limits (see the guardrails).
- **Therefore, discovery is social, not technical.** A share becomes findable
  only when a human posts its link somewhere public. The information Sift can
  ever know about is exactly "links that appeared in public posts."

The consequence is liberating: because the only inputs are already-public links,
the ethical version of this tool and the *only feasible* version of this tool are
the same tool.

## Reframing the goal

"Search Mega and Drive" decomposes into three tractable sub-problems:

1. **Discovery** — Find the public posts that contain share links, and extract
   the links. This is a crawling/harvesting problem over forums, chat exports,
   paste sites, social media, and search-engine results.

2. **Enrichment** — For a given public link, read what is *inside* it without
   downloading: the folder's file names, sizes, and types, plus whether it is
   alive. Both Mega and Drive expose enough metadata for a public link to do
   this cheaply.

3. **Search** — Index the enriched metadata (filenames + the context text the
   link was posted with) and serve typo-tolerant, faceted search over it.

The rest of the docs take these one at a time.

## What "good" looks like for an MVP

A thin end-to-end slice that proves the pipeline:

- Harvest Mega + Drive links from **one or two** public sources (e.g. a subreddit
  and a set of search-engine dorks).
- Enrich each with folder metadata and an alive/dead flag.
- Index into a search engine and expose a `/search` endpoint.
- Re-validate liveness on a schedule.

Everything else (more sources, ranking, a polished UI, more providers) is
iteration on top of that slice. See [`07-roadmap.md`](./07-roadmap.md).
