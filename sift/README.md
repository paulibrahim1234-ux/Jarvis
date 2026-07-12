# Sift

**An OSINT aggregator and search index for publicly shared cloud-storage links.**

Sift discovers, validates, and indexes file-share links (Mega.nz, Google Drive,
and others) that people have **already posted publicly** — on forums, Telegram
channels, Reddit, paste sites, and the open web — and makes them searchable by
filename, content type, and context.

The goal is research and situational awareness: understanding *what is publicly
reachable online and how exposed it is*. Sift is a discovery layer over links
that are already in the open. It is **not** a tool for breaking access controls.

> Status: **design / brainstorm phase.** This directory currently contains the
> project brief and architecture notes. See [`docs/`](./docs) for the full
> thinking. No harvesters or indexers are implemented yet.

---

## The core insight

You cannot crawl Mega or Google Drive. Neither service publishes a directory of
shared links — that is by design. A share link is only discoverable if a human
*posted it somewhere public*.

So "search Mega/Drive" is really **three** separate problems:

1. **Discovery** — harvest share links from the public places people post them.
2. **Enrichment** — for each link, read its *metadata* (file/folder names,
   sizes, types) without downloading, and check whether it is still alive.
3. **Search** — index that metadata and make it query-able.

Sift is fundamentally a specialized search engine whose crawl frontier is
"public posts that contain share links," not the storage providers themselves.
This is also why the only feasible approach is the ethical one: there is no way
to enumerate private shares, so Sift never tries.

---

## What Sift does and does not do

| Does | Does not |
| --- | --- |
| Index links already posted in public | Guess, brute-force, or crack share keys |
| Read public folder metadata via provider APIs | Download or re-host any file content |
| Track whether a link is alive or dead | Bypass any authentication or access control |
| Support takedown / removal requests | Deliberately surface illegal material |
| Respect provider rate limits and ToS | Hammer APIs or scrape aggressively |

The legal and ethical boundaries are not an afterthought — they shape the
architecture. See [`docs/06-legal-ethics-safety.md`](./docs/06-legal-ethics-safety.md).

---

## Repository layout (planned)

```
sift/
├── README.md            ← you are here
├── CLAUDE.md            ← project context for Claude Code
└── docs/
    ├── 00-overview.md            The problem and the core insight
    ├── 01-architecture.md        Pipeline, components, tech choices
    ├── 02-data-model.md          Canonical schema for links & metadata
    ├── 03-link-discovery.md      Where links come from and how to harvest
    ├── 04-metadata-extraction.md Reading Mega/Drive metadata without downloading
    ├── 05-indexing-and-search.md The search layer and ranking
    ├── 06-legal-ethics-safety.md Guardrails that constrain the design
    └── 07-roadmap.md             Phased plan, starting with a thin MVP
```

## Relationship to Jarvis

Sift currently lives inside the [Jarvis](../README.md) repository during the
design phase because repo-creation access was not available when it was
scaffolded. It is written to be **fully self-contained** so it can be extracted
into its own repository with a single command once that access exists:

```bash
git subtree split --prefix=sift -b sift-standalone
# then push sift-standalone to the new repo's main branch
```

Nothing in Sift imports from Jarvis.
