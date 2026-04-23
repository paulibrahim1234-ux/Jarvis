"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  fetchSpotify,
  searchSpotify,
  playSpotifyURI,
  controlSpotify,
  setSpotifyVolume,
} from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface Track {
  title: string;
  name?: string;
  artist: string;
  album: string;
  album_art?: string | null;
  duration_ms: number;
  progress_ms: number;
  progress: number;
  is_playing: boolean;
  volume?: number | null;
  uri?: string | null;
}

interface QueueItem {
  title: string;
  artist: string;
  album?: string;
  album_art?: string | null;
  duration_ms?: number;
  uri?: string | null;
}

interface Playlist {
  name: string;
  uri: string;
  id: string;
  cover?: string | null;
  track_count: number;
  owner?: string | null;
}

interface RecentItem extends QueueItem {
  played_at?: string;
}

interface SpotifyPayload {
  available: boolean;
  source?: string | null;
  track: Track | null;
  album_art_url: string | null;
  web_api_connected: boolean;
  auth_url: string | null;
  queue: QueueItem[] | null;
  playlists: Playlist[] | null;
  recently_played: RecentItem[] | null;
}

type Tab = "now" | "library" | "recent" | "search" | "queue";

// ── Component ────────────────────────────────────────────────────────────────

export function SpotifyWidget() {
  // Tile-level ref so size reflects the WHOLE widget tile, not just the
  // inner content of whichever conditional branch happens to render. This
  // prevents the compact-mode lock-in bug where the compact layout's
  // smaller content height kept us in compact mode forever.
  const tileRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [payload, setPayload] = useState<SpotifyPayload | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [live, setLive] = useState(false);
  const [progressMs, setProgressMs] = useState(0);
  const [tab, setTab] = useState<Tab>("now");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<QueueItem[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Resize observer on the OUTER tile (stable across branch swaps).
  useEffect(() => {
    const node = tileRef.current;
    if (!node) return;
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setSize({ w: Math.round(width), h: Math.round(height) });
    });
    obs.observe(node);
    return () => obs.disconnect();
  }, []);

  // Poll the backend (every 5s per spec)
  const poll = useCallback(() => {
    fetchSpotify()
      .then((data: SpotifyPayload) => {
        setPayload(data);
        if (data.track) {
          setTrack(data.track);
          setProgressMs(data.track.progress_ms);
          setLive(true);
        } else if (!data.available) {
          setLive(false);
        }
      })
      .catch(() => {
        /* backend offline */
      });
  }, []);

  useEffect(() => {
    poll();
    // 10s is plenty for now-playing UI; 5s was over-fetching during heavy
    // backend AppleScript work elsewhere on the dashboard.
    const id = setInterval(poll, 10_000);
    return () => clearInterval(id);
  }, [poll]);

  // Tick progress locally between polls
  useEffect(() => {
    if (!live || !track?.is_playing) return;
    const id = setInterval(() => {
      if (!track) return;
      setProgressMs((p) => Math.min(p + 1000, track.duration_ms));
    }, 1000);
    return () => clearInterval(id);
  }, [live, track?.is_playing, track?.duration_ms]);

  const webOk = Boolean(payload?.web_api_connected);

  // If web api is not connected, force Now Playing tab
  useEffect(() => {
    if (!webOk && tab !== "now") setTab("now");
  }, [webOk, tab]);

  // ── Controls ──────────────────────────────────────────────────────────────

  async function onToggle() {
    if (!track) return;
    const nextCmd = track.is_playing ? "pause" : "play";
    try {
      await controlSpotify(nextCmd);
      setTrack((t) => (t ? { ...t, is_playing: !t.is_playing } : t));
      setTimeout(poll, 700);
    } catch {
      /* ignore */
    }
  }

  async function onNext() {
    try {
      await controlSpotify("next");
      setTimeout(poll, 700);
    } catch {
      /* ignore */
    }
  }

  async function onPrev() {
    try {
      await controlSpotify("previous");
      setTimeout(poll, 700);
    } catch {
      /* ignore */
    }
  }

  async function onVolume(v: number) {
    setTrack((t) => (t ? { ...t, volume: v } : t));
    try {
      await setSpotifyVolume(v);
    } catch {
      /* ignore */
    }
  }

  async function onPlayUri(uri: string) {
    if (!uri) return;
    try {
      await playSpotifyURI(uri);
      setTimeout(poll, 1200);
    } catch {
      /* ignore */
    }
  }

  // Debounced search (300ms per spec)
  useEffect(() => {
    if (!webOk) {
      setSearchResults(null);
      return;
    }
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    const id = setTimeout(async () => {
      try {
        const data = await searchSpotify(trimmed, 20);
        setSearchResults(data.results ?? []);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(id);
  }, [searchQuery, webOk]);

  // ── Computed ──────────────────────────────────────────────────────────────

  const progress = track && track.duration_ms > 0 ? progressMs / track.duration_ms : 0;
  const fmt = (ms: number) => {
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  const isNarrow = size.w > 0 && size.w < 340;
  // Compact strip layout only for truly tiny tiles. The default dashboard
  // tile is ~240px tall (inner content ~190px after header), and tabs +
  // a small album thumb fit comfortably above that. Threshold lowered
  // from 200 -> 130 so default-sized widgets show the tabbed UI.
  const isCompact = size.h > 0 && size.h < 130;

  const visibleTabs: { key: Tab; label: string }[] = useMemo(() => {
    const base: { key: Tab; label: string }[] = [{ key: "now", label: "Now" }];
    if (webOk) {
      base.push({ key: "library", label: "Library" });
      base.push({ key: "recent", label: "Recent" });
      base.push({ key: "search", label: "Search" });
      base.push({ key: "queue", label: "Queue" });
    }
    return base;
  }, [webOk]);

  // ── Compact layout — preserve original now-playing appearance ─────────────

  if (isCompact) {
    return (
      <Card ref={tileRef} className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors overflow-hidden">
        <Header live={live} webOk={webOk} authUrl={payload?.auth_url} />
        <CardContent ref={contentRef} className="flex-1 min-h-0 px-3 py-2">
          {!track ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <p className="text-sm text-muted-foreground">Nothing playing</p>
              <p className="text-xs text-muted-foreground/70">Start a track in Spotify</p>
            </div>
          ) : (
            <div className="flex items-center gap-3 h-full">
              <AlbumArt src={track.album_art} size="h-12 w-12" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{track.title}</p>
                <p className="text-xs text-muted-foreground truncate">{track.artist}</p>
                <div className="mt-1 h-1 w-full rounded-full bg-white/10 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#1DB954]"
                    style={{ width: `${progress * 100}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center gap-1">
                <IconButton onClick={onPrev} label="Previous">
                  <PrevIcon />
                </IconButton>
                <PlayButton isPlaying={track.is_playing} onToggle={onToggle} size="sm" />
                <IconButton onClick={onNext} label="Next">
                  <NextIcon />
                </IconButton>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // ── Full layout ───────────────────────────────────────────────────────────

  return (
    <Card ref={tileRef} className="h-full flex flex-col rounded-xl border border-white/10 bg-card hover:border-white/15 transition-colors overflow-hidden">
      <Header live={live} webOk={webOk} authUrl={payload?.auth_url} />
      <CardContent
        ref={contentRef}
        className="flex-1 min-h-0 px-3 pb-2 pt-1 overflow-hidden flex flex-col gap-1.5"
      >
        {/* Tab strip */}
        <div className="flex items-center gap-0 border-b border-white/10 overflow-x-auto no-scrollbar">
          {visibleTabs.map((t) => (
            <TabBtn
              key={t.key}
              active={tab === t.key}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </TabBtn>
          ))}
          {!webOk && payload?.auth_url && (
            <a
              href={payload.auth_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto text-[10px] text-[#1DB954] hover:underline whitespace-nowrap px-2"
            >
              Connect Spotify Web API
            </a>
          )}
        </div>

        {/* Content area */}
        <div className="flex-1 min-h-0 overflow-hidden mt-0.5">
          {tab === "now" && !track ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <p className="text-sm text-muted-foreground">Nothing playing</p>
              <p className="text-xs text-muted-foreground/70">Start a track in Spotify</p>
            </div>
          ) : tab === "now" && track ? (
            <NowPlayingPane
              track={track}
              progressMs={progressMs}
              progress={progress}
              fmt={fmt}
              isNarrow={isNarrow}
              onPrev={onPrev}
              onNext={onNext}
              onToggle={onToggle}
              onVolume={onVolume}
            />
          ) : null}
          {tab === "library" && (
            <LibraryPane
              items={payload?.playlists ?? null}
              webOk={webOk}
              isNarrow={isNarrow}
              onPlay={onPlayUri}
            />
          )}
          {tab === "recent" && (
            <RecentPane
              items={payload?.recently_played ?? null}
              webOk={webOk}
              onPlay={onPlayUri}
            />
          )}
          {tab === "search" && (
            <SearchPane
              query={searchQuery}
              setQuery={setSearchQuery}
              results={searchResults}
              searching={searching}
              webOk={webOk}
              onPlay={onPlayUri}
            />
          )}
          {tab === "queue" && (
            <QueuePane
              items={payload?.queue ?? null}
              webOk={webOk}
              onPlay={onPlayUri}
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Panes ────────────────────────────────────────────────────────────────────

function NowPlayingPane({
  track,
  progressMs,
  progress,
  fmt,
  isNarrow,
  onPrev,
  onNext,
  onToggle,
  onVolume,
}: {
  track: Track;
  progressMs: number;
  progress: number;
  fmt: (ms: number) => string;
  isNarrow: boolean;
  onPrev: () => void;
  onNext: () => void;
  onToggle: () => void;
  onVolume: (v: number) => void;
}) {
  return (
    <div className="h-full flex flex-col gap-2 overflow-hidden">
      {/* Album art + title row — always horizontal */}
      <div className="flex flex-row gap-3 items-center">
        <AlbumArt src={track.album_art} size="h-14 w-14" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold truncate text-sm leading-tight">{track.title}</p>
          <p className="text-xs text-muted-foreground truncate">{track.artist}</p>
          <p className="text-[10px] text-muted-foreground/50 truncate">{track.album}</p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full rounded-full bg-[#1DB954] transition-all duration-1000"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground/50 tabular-nums">
          <span>{fmt(progressMs)}</span>
          <span>{fmt(track.duration_ms)}</span>
        </div>
      </div>

      {/* Controls + volume in one horizontal row */}
      <div className="flex items-center gap-2">
        <IconButton onClick={onPrev} label="Previous">
          <PrevIcon />
        </IconButton>
        <PlayButton isPlaying={track.is_playing} onToggle={onToggle} size="sm" />
        <IconButton onClick={onNext} label="Next">
          <NextIcon />
        </IconButton>
        {typeof track.volume === "number" && (
          <div className="flex items-center gap-1 text-muted-foreground ml-1">
            <VolumeIcon />
            <input
              type="range"
              min={0}
              max={100}
              value={track.volume ?? 0}
              onChange={(e) => onVolume(Number(e.target.value))}
              className="w-16 accent-[#1DB954]"
              aria-label="Volume"
            />
          </div>
        )}
      </div>
    </div>
  );
}

function LibraryPane({
  items,
  webOk,
  isNarrow,
  onPlay,
}: {
  items: Playlist[] | null;
  webOk: boolean;
  isNarrow: boolean;
  onPlay: (uri: string) => void;
}) {
  if (!webOk) return <Empty text="Connect Spotify to see your playlists" />;
  if (!items) return <Empty text="Loading…" />;
  if (items.length === 0) return <Empty text="No playlists" />;
  return (
    <div className="h-full overflow-auto pr-1">
      <ul className="space-y-0.5">
        {items.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => onPlay(p.uri)}
              className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-white/5 text-left"
              title={p.name}
            >
              {p.cover ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.cover}
                  alt=""
                  className="h-8 w-8 rounded object-cover shrink-0"
                />
              ) : (
                <div className="h-8 w-8 rounded bg-gradient-to-br from-emerald-900 to-teal-700 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate">{p.name}</p>
                <p className="truncate text-[10px] text-muted-foreground/60">
                  {p.owner ? `${p.owner} • ` : ""}{p.track_count} tracks
                </p>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecentPane({
  items,
  webOk,
  onPlay,
}: {
  items: RecentItem[] | null;
  webOk: boolean;
  onPlay: (uri: string) => void;
}) {
  if (!webOk) return <Empty text="Connect Spotify to see recently played" />;
  if (!items) return <Empty text="Loading…" />;
  if (items.length === 0) return <Empty text="Nothing recent" />;
  return (
    <div className="h-full overflow-auto pr-1">
      <ul className="space-y-0.5">
        {items.map((t, i) => (
          <li key={(t.uri ?? "") + i}>
            <button
              onClick={() => t.uri && onPlay(t.uri)}
              className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-white/5 text-left"
            >
              {t.album_art ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={t.album_art}
                  alt=""
                  className="h-7 w-7 rounded object-cover shrink-0"
                />
              ) : (
                <div className="h-7 w-7 rounded bg-neutral-800 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate">{t.title}</p>
                <p className="truncate text-[10px] text-muted-foreground/60">
                  {t.artist}
                </p>
              </div>
              {t.played_at && (
                <span className="text-[9px] text-muted-foreground/50 shrink-0">
                  {relTime(t.played_at)}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SearchPane({
  query,
  setQuery,
  results,
  searching,
  webOk,
  onPlay,
}: {
  query: string;
  setQuery: (q: string) => void;
  results: QueueItem[] | null;
  searching: boolean;
  webOk: boolean;
  onPlay: (uri: string) => void;
}) {
  if (!webOk) return <Empty text="Connect Spotify to search" />;
  return (
    <div className="h-full flex flex-col gap-1.5">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search songs, artists, albums…"
          className="w-full rounded-md bg-white/5 border border-white/10 px-2 py-1 text-xs placeholder:text-muted-foreground/50 focus:outline-none focus:border-[#1DB954]/60"
          autoFocus
        />
        {searching && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground/60">
            …
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-auto pr-1">
        {!query.trim() ? (
          <Empty text="Type to search Spotify" />
        ) : results === null ? (
          <Empty text="…" />
        ) : results.length === 0 ? (
          <Empty text="No results" />
        ) : (
          <ul className="space-y-0.5">
            {results.map((t, i) => (
              <li key={(t.uri ?? "") + i}>
                <button
                  onClick={() => t.uri && onPlay(t.uri)}
                  className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-white/5 text-left"
                >
                  {t.album_art ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={t.album_art}
                      alt=""
                      className="h-7 w-7 rounded object-cover shrink-0"
                    />
                  ) : (
                    <div className="h-7 w-7 rounded bg-neutral-800 shrink-0" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{t.title}</p>
                    <p className="truncate text-[10px] text-muted-foreground/60">
                      {t.artist}
                      {t.album ? ` • ${t.album}` : ""}
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function QueuePane({
  items,
  webOk,
  onPlay,
}: {
  items: QueueItem[] | null;
  webOk: boolean;
  onPlay: (uri: string) => void;
}) {
  if (!webOk) return <Empty text="Connect Spotify to see upcoming tracks" />;
  if (!items) return <Empty text="Loading…" />;
  if (items.length === 0)
    return <Empty text="Queue is empty — play something to fill it" />;
  return (
    <div className="h-full overflow-auto pr-1">
      <ul className="space-y-0.5">
        {items.map((t, i) => (
          <li key={(t.uri ?? "") + i}>
            <button
              onClick={() => t.uri && onPlay(t.uri)}
              className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-white/5 text-left"
            >
              <span className="text-muted-foreground/40 tabular-nums w-4 text-[10px]">
                {i + 1}
              </span>
              {t.album_art ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={t.album_art}
                  alt=""
                  className="h-6 w-6 rounded object-cover shrink-0"
                />
              ) : (
                <div className="h-6 w-6 rounded bg-neutral-800 shrink-0" />
              )}
              <span className="truncate flex-1">{t.title}</span>
              <span className="text-muted-foreground/60 truncate text-[10px]">
                {t.artist}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Shared sub-components ────────────────────────────────────────────────────

function Header({
  live,
  webOk,
  authUrl,
}: {
  live: boolean;
  webOk: boolean;
  authUrl?: string | null;
}) {
  return (
    <CardHeader className="px-3 pt-2 pb-1">
      <CardTitle className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <svg className="h-4 w-4 text-[#1DB954]" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
        </svg>
        Spotify
        {live && (
          <span
            className="h-1.5 w-1.5 rounded-full bg-emerald-400 inline-block ml-1"
            title="Live"
          />
        )}
        {!webOk && authUrl && (
          <a
            href={authUrl}
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-[10px] normal-case font-normal text-[#1DB954] hover:underline"
          >
            connect web api
          </a>
        )}
      </CardTitle>
    </CardHeader>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <p className="px-2 py-3 text-[11px] text-muted-foreground/60">{text}</p>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-0.5 text-[10px] transition-colors whitespace-nowrap ${
        active
          ? "text-foreground border-b-2 border-[#1DB954] -mb-px"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function AlbumArt({ src, size }: { src?: string | null; size: string }) {
  if (src)
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt="album"
        className={`${size} shrink-0 rounded-lg object-cover shadow-lg`}
      />
    );
  return (
    <div
      className={`${size} shrink-0 rounded-lg bg-gradient-to-br from-emerald-900 via-emerald-800 to-teal-700 shadow-lg`}
    />
  );
}

function PlayButton({
  isPlaying,
  onToggle,
  size,
}: {
  isPlaying: boolean;
  onToggle: () => void;
  size: "sm" | "lg";
}) {
  const cls =
    size === "lg"
      ? "h-10 w-10 rounded-full bg-white flex items-center justify-center hover:scale-105 transition-transform"
      : "shrink-0 h-8 w-8 rounded-full bg-white/10 hover:bg-white/15 flex items-center justify-center transition-colors";
  const iconCls = size === "lg" ? "h-5 w-5 text-black" : "h-3.5 w-3.5";
  return (
    <button
      onClick={onToggle}
      className={cls}
      aria-label={isPlaying ? "Pause" : "Play"}
    >
      {isPlaying ? (
        <svg className={iconCls} fill="currentColor" viewBox="0 0 24 24">
          <rect x="6" y="4" width="4" height="16" />
          <rect x="14" y="4" width="4" height="16" />
        </svg>
      ) : (
        <svg
          className={`${iconCls} ml-0.5`}
          fill="currentColor"
          viewBox="0 0 24 24"
        >
          <path d="M8 5v14l11-7z" />
        </svg>
      )}
    </button>
  );
}

function IconButton({
  onClick,
  children,
  label,
}: {
  onClick: () => void;
  children: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className="text-muted-foreground hover:text-foreground transition-colors p-1"
    >
      {children}
    </button>
  );
}

function PrevIcon() {
  return (
    <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
    </svg>
  );
}
function NextIcon() {
  return (
    <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
    </svg>
  );
}
function VolumeIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 8.05v7.9A4.5 4.5 0 0 0 16.5 12z" />
    </svg>
  );
}

// ── Utils ────────────────────────────────────────────────────────────────────

function relTime(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const diff = Date.now() - then;
    if (!isFinite(diff) || diff < 0) return "";
    const m = Math.floor(diff / 60000);
    if (m < 1) return "now";
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    const d = Math.floor(h / 24);
    return `${d}d`;
  } catch {
    return "";
  }
}
