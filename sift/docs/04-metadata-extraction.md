# 04 — Metadata extraction (enrichment)

Given a public link, read what is inside it — file names, sizes, types, structure
— **without downloading content**, and determine whether it is alive. This is
what turns a bare URL into something searchable.

## Mega.nz

A public Mega folder link carries everything needed to *list* the folder: the
folder id plus the decryption key in the URL fragment. Mega's client API lets you
fetch the encrypted node tree and decrypt names/sizes locally using that key —
all without downloading file payloads.

- **Tools:** existing Python SDKs (e.g. `mega.py`) or the `megatools` /
  MEGAcmd family expose "list folder" style operations. Evaluate which handles
  the current link formats and large folders best; the community libraries vary
  in maintenance.
- **What you get:** the full tree — file/folder names, sizes, and structure.
  Types are inferred from extensions (Mega doesn't store MIME).
- **Cost:** listing is cheap (metadata only). Downloading is what is expensive
  and bandwidth-metered — Sift never does it.
- **Liveness:** if the folder no longer resolves (removed/banned), listing fails
  with a specific error → mark `alive = false`.
- **Care:** the key is required and sensitive-ish. It came from a public post, but
  keep it out of casual logs (see data-model note).

## Google Drive

Behavior depends on how the folder was shared.

- **"Anyone with the link" folders:** the Drive API `files.list` with a
  `'<folderId>' in parents` query can enumerate children (names, sizes,
  mimeType, nesting) using an API key / OAuth app — no download. This is the
  clean path when it works.
- **Fallback:** the public folder web view (`/drive/folders/<id>`) renders the
  listing; it can be parsed, but it is brittle and more ToS-sensitive than the
  API. Prefer the API.
- **Single-file links:** `files.get` returns name, size, mimeType, owner-limited
  metadata.
- **Liveness:** a `404`/`403` on the id → `alive = false` (dead vs. access-
  revoked can be distinguished by the error).
- **Quotas:** the Drive API is quota-limited. Batch, cache, and throttle;
  schedule enrichment to stay well under quota.

## Other providers (later)

MediaFire, Dropbox, 1fichier, etc. Each needs its own adapter with the same
interface: `enrich(link) -> items[] + alive`. Add providers only after the
Mega + Drive path is solid.

## Enricher contract

```
enrich(link) -> {
   alive: bool,
   items: [ { path, name, is_dir, size_bytes, mime_or_ext } ],
   checked_at: timestamp,
   error: optional structured reason
}
```

- **Metadata only.** Never fetch file bytes.
- **Bounded.** Cap items per folder (huge shares) and total work per run; record
  when a listing was truncated rather than hanging.
- **Idempotent & resumable.** Safe to re-run; updates `item` rows in place.
- **Rate-limited per provider.** Respect quotas and back off on errors.
- **Fail closed.** On ambiguous errors, mark unknown rather than guessing alive.

## Why listing-without-downloading is both key and legitimate

The whole product hinges on reading *metadata* of already-public links. That is
exactly what a person clicking the public link would see (the folder listing),
just automated and indexed. Sift never accesses anything a visitor to the public
link could not already see, and never pulls the actual files.
