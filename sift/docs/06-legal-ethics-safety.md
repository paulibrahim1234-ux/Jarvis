# 06 — Legal, ethics, and safety

These are not a disclaimer stapled to the end. They constrain the architecture,
and several of them are the reason the design looks the way it does. Read this
before building anything.

## The bright lines (never cross)

1. **Only already-public links.** Sift ingests links that humans posted in
   public. It never guesses, brute-forces, or enumerates folder IDs or
   decryption keys. (This is also why it works at all — private shares are not
   enumerable.)
2. **Metadata only, never content.** Sift stores names, sizes, types, liveness.
   It never downloads, mirrors, proxies, or re-hosts a single file.
3. **No access-control bypass.** Password-protected or login-gated shares stop at
   the gate. Sift accesses only what a visitor to the public link already sees.
4. **Exclusion, not curation of the illegal.** Filtering exists to *keep bad
   content out*, never to find it. There is no feature whose purpose is to
   surface illegal material, and requests to add one are refused.
5. **Be a polite netizen.** Respect provider ToS, `robots.txt`, API quotas, and
   rate limits everywhere.

## The legal landscape (be honest about it)

- **Copyright / DMCA.** A lot of what circulates on these lockers is
  copyright-infringing (books, courses, media). Indexing *links* to infringing
  material is legally contested and varies by jurisdiction — it is the same
  exposure that link-index sites face and get takedowns/lawsuits over. Sift
  reduces (does not eliminate) this by storing only metadata and by treating
  takedowns as first-class. Anyone operating an instance should understand this
  risk in their jurisdiction and get advice if operating publicly.
- **Provider Terms of Service.** Automated access to Mega, Google, Reddit,
  Telegram, etc. is governed by their ToS; scraping may breach them even where it
  isn't otherwise illegal. Prefer official APIs; honor their limits.
- **Computer-misuse law.** Staying strictly on the "only public, no
  access-control bypass, no download" side of the lines above is what keeps this
  an OSINT/research tool rather than unauthorized access. Do not drift across it
  for convenience.

## Safety: the ugly reality of anonymous file lockers

Anonymous lockers are abused to host genuinely harmful and illegal material,
including CSAM. A tool that harvests links from public dumps *will* encounter
references to it. This must be designed for, not discovered later:

- **Exclusion blocklists** on filenames, context keywords, and known-bad
  identifiers — applied at harvest and enrich time to drop matches before they
  are ever indexed.
- **Never surface, and route for reporting.** Anything matching known-illegal
  signals is dropped from the pipeline and, where legally appropriate,
  surfaced to the operator for reporting to the relevant authority
  (e.g. NCMEC in the US) — never shown in search.
- **No thumbnails, no previews, no content.** Metadata-only isn't just a scope
  choice; it's a safety property.
- **Human-review path** for the reporting/takedown queue.

If you cannot commit to these safeguards, do not run a public instance.

## Takedown / removal as a feature

- A public report endpoint and `report` table (see data model).
- Reasons: DMCA, illegal content, privacy, owner request.
- On action, the link is flagged `takedown = true`, immediately removed from the
  index, and excluded from all serving — before any slower cleanup.
- Keep an auditable record of what was actioned and why.

## Operating posture

- **Private by default** while in research/design (the repo is private).
- **Robots and rate limits respected** as a rule, not a nicety.
- **Logs mind sensitive fields** (Mega keys) — public-sourced, but don't spray
  them around.
- **Document every source and provider** you add, including its ToS posture.

## One-line summary

Sift indexes *pointers that are already public*, stores *metadata not content*,
*excludes* the illegal rather than seeking it, and *honors takedowns first*.
Keep it on that side of every line and it stays a research tool.
