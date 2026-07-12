# 03 — Link discovery (harvesting)

The crawl frontier is **public posts that contain share links**, not the storage
providers. This doc catalogs where those posts live and how to harvest them
responsibly.

## What a share link looks like (for extraction)

Regex/URL patterns to detect in post text:

- **Mega:** `https://mega.nz/folder/<id>#<key>`, `https://mega.nz/file/<id>#<key>`,
  and legacy `https://mega.nz/#F!<id>!<key>` / `#!<id>!<key>`.
- **Google Drive:** `https://drive.google.com/drive/folders/<id>`,
  `https://drive.google.com/file/d/<id>/view`, `.../open?id=<id>`.
- **MediaFire / others (later):** `https://www.mediafire.com/folder/<id>`, etc.

Extract the URL *and* the surrounding context text (title, body, nearby lines) —
context is a primary search signal since filenames alone are often terse.

## Sources, roughly in order of value

### Search-engine dorks (cheapest first step)
Queries like `site:mega.nz`, `"mega.nz/folder"`, `site:drive.google.com/drive/folders`,
combined with topic terms. Reality check: Google actively delists a lot of these,
and result pages are rate-limited and ToS-sensitive. Treat as *one* source, not
the backbone. Consider search APIs (Bing, Brave, SerpAPI) over scraping SERPs.

### Reddit
Many communities post share links. `praw` against the official API, polling
target subreddits and searching for provider domains. Cheap, structured,
rate-limited but well-documented. Good first real harvester.

### Telegram
A huge amount of link-sharing happens in public channels/groups. `telethon` can
read public channels you join. High yield, but: respect Telegram ToS, only public
channels, and be careful about what those channels contain (see safety doc).

### Paste sites
Pastebin and similar host link dumps. Public scraping APIs are limited; some
offer firehoses. Moderate value, moderate effort.

### Forums / imageboards / link-index sites
Topic-specific forums and existing link-index sites aggregate shares. Per-site
scrapers; respect `robots.txt` and rate limits. Higher effort, sometimes high
yield for a niche.

### Social (X, etc.)
Possible but increasingly API-hostile and expensive. Low priority.

## Harvester contract

Every harvester should:

1. **Be resumable.** Persist a per-source cursor (last id / timestamp) so restarts
   don't re-scan or miss.
2. **Be polite.** Honor each source's rate limits, `robots.txt`, and API ToS.
   Backoff on 429/errors. Prefer official APIs to scraping.
3. **Do one job.** Emit `sighting` rows (raw url + context + timestamps). No
   enrichment, no validation — those are downstream stages.
4. **Treat input as untrusted.** Post bodies and filenames are attacker-
   controllable. Sanitize before storage/rendering; never execute or fetch
   arbitrary embedded content during harvest.

## Deliberately out of scope

- No guessing or enumerating link IDs/keys — links come only from real posts.
- No scraping behind logins/paywalls or private channels.
- No aggressive crawling that would amount to a nuisance to a source site.
