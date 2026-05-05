"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { WidgetWrapper, type WidgetStatus } from "@/components/layout/widget-wrapper";
import Skeleton from "@/components/ui/skeleton";
import {
  Library,
  ListMusic,
  Search,
  Music,
} from "lucide-react";
import {
  fetchSpotify,
  fetchSpotifyHome,
  searchSpotify,
  playSpotifyURI,
  playSpotifyContext,
  controlSpotify,
  setSpotifyVolume,
} from "@/lib/api";
import {
  type Mood,
  DEFAULT_MOODS,
  loadMoods,
  saveMoods,
  resetMoods,
  extractPlaylistId,
} from "@/data/moods";
import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";

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

type Tab = "home" | "moods" | "now" | "library" | "search" | "queue";


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
  const [lastUpdated, setLastUpdated] = useState<number | undefined>(undefined);
  const [widgetStatus, setWidgetStatus] = useState<WidgetStatus | undefined>(undefined);
  const [progressMs, setProgressMs] = useState(0);
  const [tab, setTab] = useState<Tab>("now");
  const [homeData, setHomeData] = useState<Awaited<ReturnType<typeof fetchSpotifyHome>> | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<QueueItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [moods, setMoods] = useState<Mood[]>(() => loadMoods());
  const [playError, setPlayError] = useState<string | null>(null);
  const trackRef = useRef<Track | null>(null);

  // Keeps statusRef current so the freshness effect can read it without
  // adding widgetStatus to its own deps (which caused a restart loop — D2).
  const statusRef = useRef(widgetStatus);
  useEffect(() => { statusRef.current = widgetStatus; }, [widgetStatus]);

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

  // Poll the backend (every 10s)
  const poll = useCallback(() => {
    fetchSpotify()
      .then((data: SpotifyPayload) => {
        setPayload(data);
        if (data.track) {
          setTrack(data.track);
          trackRef.current = data.track;
          setProgressMs(data.track.progress_ms);
          setLive(true);
        } else if (!data.available) {
          setLive(false);
        }
        const now = Date.now();
        setLastUpdated(now);
        setWidgetStatus("fresh");
      })
      .catch(() => {
        setWidgetStatus("error");
      });
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      poll();
    }, 10_000);
    return () => clearInterval(id);
  }, [poll]);

  // Promote status to stale after 5 minutes without a successful fetch.
  // widgetStatus intentionally omitted — statusRef carries the current value
  // so this effect doesn't restart when status changes (D2).
  useEffect(() => {
    if (!lastUpdated) return;
    const check = () => {
      if (statusRef.current === "error") return;
      const age = Date.now() - lastUpdated;
      setWidgetStatus(age < 5 * 60 * 1000 ? "fresh" : "stale");
    };
    check();
    const id = setInterval(check, 60_000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  // Tick progress locally between polls — read duration from ref to avoid
  // stale closure: when the track changes, the ref updates synchronously
  // while the interval's captured `track` value would lag one render cycle,
  // causing progress to momentarily exceed 100%.
  useEffect(() => {
    if (!live || !track?.is_playing) return;
    const id = setInterval(() => {
      const currentTrack = trackRef.current;
      if (!currentTrack) return;
      setProgressMs((p) => Math.min(p + 1000, currentTrack.duration_ms));
    }, 1000);
    return () => clearInterval(id);
  }, [live, track?.is_playing]);

  const webOk = Boolean(payload?.web_api_connected);

  // When web api connects, switch to Home. When it disconnects, revert to Now.
  useEffect(() => {
    if (webOk && tab === "now") setTab("home");
    if (!webOk && tab !== "now") setTab("now");
  }, [webOk]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load home data when on home tab and web api is connected.
  // Guard with `alive` so a response that arrives after a tab-switch
  // (or unmount) cannot overwrite a newer response with stale data.
  useEffect(() => {
    if (tab === "home" && webOk) {
      let alive = true;
      fetchSpotifyHome().then((d) => { if (alive) setHomeData(d); }).catch(() => {});
      return () => { alive = false; };
    }
  }, [tab, webOk]);

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
      if (
        uri.startsWith("spotify:playlist:") ||
        uri.startsWith("spotify:album:") ||
        uri.startsWith("spotify:artist:")
      ) {
        const res = await playSpotifyContext(uri);
        if (res && res.ok === false) {
          setPlayError(res.message || res.error || "Playback failed");
          setTimeout(() => setPlayError(null), 6000);
          return;
        }
      } else {
        await playSpotifyURI(uri);
      }
      setPlayError(null);
      setTimeout(poll, 1200);
    } catch {
      setPlayError("Couldn't reach Jarvis backend — try again.");
      setTimeout(() => setPlayError(null), 6000);
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
  const isCompact = size.h > 0 && size.h < 130;

  const visibleTabs: { key: Tab; label: string }[] = useMemo(() => {
    const base: { key: Tab; label: string }[] = [];
    if (webOk) {
      base.push({ key: "home", label: "Home" });
      base.push({ key: "moods", label: "Moods" });
      base.push({ key: "library", label: "Library" });
      base.push({ key: "search", label: "Search" });
      base.push({ key: "queue", label: "Queue" });
    }
    base.push({ key: "now", label: "Now" });
    return base;
  }, [webOk]);

  // ── Compact layout — preserve original now-playing appearance ─────────────

  if (isCompact) {
    if (!payload) {
      return (
        <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
          <Card
            ref={tileRef}
            className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card overflow-hidden"
            style={{ padding: "var(--widget-density-pad)" }}
          >
            <Skeleton className="h-full w-full" />
          </Card>
        </WidgetWrapper>
      );
    }
    return (
      <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
      <Card
        ref={tileRef}
        className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors overflow-hidden"
        style={{ padding: "var(--widget-density-pad)" }}
      >
        <Header live={live} webOk={webOk} authUrl={payload?.auth_url} />
        {/* F4 — fade in once content is loaded */}
        <CardContent ref={contentRef} className="flex-1 min-h-0 px-3 py-2 animate-in fade-in duration-200">
          {!track ? (
            <EmptyState icon={Music} title="Nothing playing" hint="Start a track in Spotify" className="h-full" />
          ) : (
            <div className="flex items-center gap-3 h-full">
              <AlbumArt src={track.album_art} size="h-12 w-12" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{track.title}</p>
                <p className="text-xs text-muted-foreground truncate">{track.artist}</p>
                <div className="mt-1 h-1 w-full rounded-full bg-foreground/10 overflow-hidden">
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
      </WidgetWrapper>
    );
  }

  // ── Full layout ───────────────────────────────────────────────────────────

  // F8 — error branch MUST come before the !payload skeleton guard; otherwise
  // it is unreachable (the skeleton return fires first when payload is null).
  if (widgetStatus === "error" && !payload) {
    return (
      <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
        <Card
          ref={tileRef}
          className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card overflow-hidden"
          style={{ padding: "var(--widget-density-pad)" }}
        >
          <Header live={live} webOk={webOk} authUrl={null} />
          <CardContent className="flex-1 min-h-0 flex items-center justify-center">
            <ErrorState message="Couldn't reach Spotify" onRetry={poll} />
          </CardContent>
        </Card>
      </WidgetWrapper>
    );
  }

  if (!payload) {
    return (
      <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
        <Card
          ref={tileRef}
          className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card overflow-hidden"
          style={{ padding: "var(--widget-density-pad)" }}
        >
          <div className="flex flex-col gap-2 p-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        </Card>
      </WidgetWrapper>
    );
  }

  return (
    <WidgetWrapper status={widgetStatus} lastUpdated={lastUpdated}>
    <Card
      ref={tileRef}
      className="h-full flex flex-col rounded-xl border border-foreground/10 bg-card hover:border-foreground/15 transition-colors overflow-hidden"
      style={{ padding: "var(--widget-density-pad)" }}
    >
      <Header live={live} webOk={webOk} authUrl={payload?.auth_url} />
      {/* F4 — fade in once content is loaded */}
      <CardContent
        ref={contentRef}
        className="flex-1 min-h-0 px-3 pb-2 pt-1 overflow-hidden flex flex-col gap-1.5 animate-in fade-in duration-200"
      >
        {playError && (
          <div
            role="alert"
            className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[11px] leading-snug text-amber-200"
          >
            {playError}
          </div>
        )}
        {/* F10 — density-aware gap on tab strip */}
        <div className="no-drag flex items-center gap-0 border-b border-foreground/10 overflow-x-auto no-scrollbar [body.density-compact_&]:gap-0">
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

        <div className="no-drag flex-1 min-h-0 overflow-hidden mt-0.5">
          {tab === "home" && (
            <HomePane data={homeData} onPlay={onPlayUri} />
          )}
          {tab === "moods" && (
            <MoodsPane
              moods={moods}
              onMoodsChange={(updated) => {
                setMoods(updated);
                saveMoods(updated);
              }}
              onPlay={onPlayUri}
            />
          )}
          {tab === "now" && !track ? (
            <EmptyState icon={Music} title="Nothing playing" hint="Start a track in Spotify" className="h-full" />
          ) : tab === "now" && track ? (
            <NowPlayingPane
              track={track}
              progressMs={progressMs}
              progress={progress}
              fmt={fmt}
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
    </WidgetWrapper>
  );
}

// ── Panes ────────────────────────────────────────────────────────────────────

type HomePayload = Awaited<ReturnType<typeof fetchSpotifyHome>>;

function HomePane({
  data,
  onPlay,
}: {
  data: HomePayload | null;
  onPlay: (uri: string) => void;
}) {
  if (!data || !data.available) {
    return <p className="px-2 py-3 text-[11px] text-muted-foreground/60">Loading home…</p>;
  }

  type HomeItem = {
    title?: string;
    name?: string;
    artist?: string;
    album_art?: string | null;
    cover?: string | null;
    uri?: string | null;
  };

  const rateLimited = data.rate_limited === true;
  const retryMin = Math.max(1, Math.ceil((data.rate_limit_retry_in_seconds ?? 0) / 60));
  const banner = rateLimited ? (
    <div
      className="mb-3 px-3 py-2 rounded-lg text-[11px] leading-snug"
      style={{
        background: "color-mix(in oklab, var(--surface-2) 80%, transparent)",
        border: "1px solid var(--border-2)",
        color: "var(--ink-2)",
      }}
      role="status"
    >
      Spotify is rate-limiting Jarvis right now (~{retryMin} min until retry).
      This usually clears on its own — no action needed.
    </div>
  ) : null;

  const rows: { label: string; items: HomeItem[] }[] = [
    ...(
      (data.recently_played ?? []).length > 0
        ? [{ label: "Recently played playlists", items: (data.recently_played ?? []) as HomeItem[] }]
        : []
    ),
    { label: "Your top tracks this month", items: (data.top_tracks ?? []) as HomeItem[] },
    { label: "Top artists", items: (data.top_artists ?? []) as HomeItem[] },
    { label: "Your playlists", items: (data.playlists ?? []) as HomeItem[] },
  ];

  return (
    // F9 — bottom fade mask so content visibly fades out instead of hard-clipping
    <div
      className="h-full overflow-y-auto space-y-3 pr-0.5"
      style={{
        WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
        maskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
      }}
    >
      {banner}
      {rows.map((row) => (
        <div key={row.label}>
          <div className="text-[11px] text-muted-foreground/60 mb-1.5 px-0.5">{row.label}</div>
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
            {/* D5 — use stable uri as key instead of array index */}
            {row.items.slice(0, 8).map((item, i) => (
              <button
                key={item.uri ?? i}
                className="flex-shrink-0 flex flex-col items-center gap-1 group/tile"
                onClick={() => { if (item.uri) onPlay(item.uri); }}
              >
                <div className="w-[64px] h-[64px] rounded-lg bg-foreground/5 overflow-hidden flex-shrink-0">
                  {(item.album_art ?? item.cover) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={(item.album_art ?? item.cover) as string} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full bg-foreground/10" />
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground/70 w-[64px] truncate text-center group-hover/tile:text-foreground transition-colors leading-tight">
                  {item.title ?? item.name}
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function MoodsPane({
  moods,
  onMoodsChange,
  onPlay,
}: {
  moods: Mood[];
  onMoodsChange: (updated: Mood[]) => void;
  onPlay: (uri: string) => void;
}) {
  const [editMode, setEditMode] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftEmoji, setDraftEmoji] = useState("");
  const [draftPlaylistId, setDraftPlaylistId] = useState("");

  function startEdit(i: number) {
    setEditingIdx(i);
    setDraftName(moods[i].name);
    setDraftEmoji(moods[i].emoji);
    setDraftPlaylistId(moods[i].playlistId);
  }

  function saveEdit() {
    if (editingIdx === null) return;
    const updated = moods.map((m, i) =>
      i === editingIdx
        ? {
            name: draftName.trim() || m.name,
            emoji: draftEmoji.trim() || m.emoji,
            playlistId: extractPlaylistId(draftPlaylistId) || m.playlistId,
          }
        : m,
    );
    onMoodsChange(updated);
    setEditingIdx(null);
  }

  function handleReset() {
    resetMoods();
    onMoodsChange([...DEFAULT_MOODS]);
    setEditMode(false);
    setEditingIdx(null);
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-1.5 shrink-0">
        <span className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">Moods</span>
        <div className="flex items-center gap-2">
          {editMode && (
            <button
              onClick={handleReset}
              className="text-[9px] text-muted-foreground/40 hover:text-muted-foreground/70 transition-colors underline"
            >
              Reset defaults
            </button>
          )}
          <button
            onClick={() => { setEditMode(!editMode); setEditingIdx(null); }}
            className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground transition-colors px-1.5 py-0.5 rounded hover:bg-foreground/5"
          >
            {editMode ? "Done" : "Edit"}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="grid grid-cols-4 gap-1.5">
          {moods.map((mood, i) => {
            if (editMode && editingIdx === i) {
              return (
                // D5 — mood items lack a stable uri; playlistId is the stable key
                <div
                  key={mood.playlistId ?? i}
                  className="col-span-4 rounded-lg bg-foreground/[0.07] border border-foreground/10 p-2 space-y-1.5 text-xs"
                >
                  <div className="flex gap-1.5">
                    <input
                      value={draftEmoji}
                      onChange={(e) => setDraftEmoji(e.target.value)}
                      placeholder="Emoji"
                      className="w-10 rounded bg-foreground/5 border border-foreground/10 px-1.5 py-0.5 text-center text-sm focus:outline-none"
                    />
                    <input
                      value={draftName}
                      onChange={(e) => setDraftName(e.target.value)}
                      placeholder="Name"
                      className="flex-1 rounded bg-foreground/5 border border-foreground/10 px-1.5 py-0.5 focus:outline-none"
                    />
                  </div>
                  <input
                    value={draftPlaylistId}
                    onChange={(e) => setDraftPlaylistId(e.target.value)}
                    placeholder="Playlist URL or ID"
                    className="w-full rounded bg-foreground/5 border border-foreground/10 px-1.5 py-0.5 focus:outline-none text-[10px]"
                  />
                  <div className="flex gap-1.5">
                    <button
                      onClick={saveEdit}
                      className="rounded bg-[#1DB954]/20 hover:bg-[#1DB954]/30 px-2 py-0.5 text-[#1DB954] transition-colors"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingIdx(null)}
                      className="rounded bg-foreground/5 hover:bg-foreground/10 px-2 py-0.5 text-muted-foreground transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              );
            }

            return (
              // D5 — use stable playlistId as key
              <div key={mood.playlistId ?? i} className="relative group/moodtile">
                <button
                  onClick={() => {
                    if (editMode) {
                      startEdit(i);
                    } else {
                      onPlay(`spotify:playlist:${mood.playlistId}`);
                    }
                  }}
                  className="w-full aspect-square max-w-[72px] mx-auto rounded-lg bg-foreground/5 hover:bg-foreground/10 transition-colors flex flex-col items-center justify-center gap-0.5"
                  title={editMode ? `Edit "${mood.name}"` : mood.name}
                >
                  <span className="text-base leading-none">{mood.emoji}</span>
                  <span className="text-[9px] text-muted-foreground/70 group-hover/moodtile:text-foreground transition-colors leading-tight px-0.5 truncate w-full text-center">
                    {mood.name}
                  </span>
                </button>
                {editMode && (
                  <div className="absolute -top-0.5 -right-0.5 h-3.5 w-3.5 rounded-full bg-foreground/10 flex items-center justify-center pointer-events-none">
                    <svg className="h-2.5 w-2.5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                    </svg>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function NowPlayingPane({
  track,
  progressMs,
  progress,
  fmt,
  onPrev,
  onNext,
  onToggle,
  onVolume,
}: {
  track: Track;
  progressMs: number;
  progress: number;
  fmt: (ms: number) => string;
  onPrev: () => void;
  onNext: () => void;
  onToggle: () => void;
  onVolume: (v: number) => void;
}) {
  return (
    <div className="h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex flex-row gap-3 items-center">
        <AlbumArt src={track.album_art} size="h-14 w-14" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold truncate text-sm leading-tight">{track.title}</p>
          <p className="text-xs text-muted-foreground truncate">{track.artist}</p>
          <p className="text-[10px] text-muted-foreground/50 truncate">{track.album}</p>
        </div>
      </div>

      <div className="space-y-0.5">
        <div className="h-1 w-full rounded-full bg-foreground/10 overflow-hidden">
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
  onPlay,
}: {
  items: Playlist[] | null;
  webOk: boolean;
  onPlay: (uri: string) => void;
}) {
  if (!webOk) return <EmptyState icon={Library} title="Connect Spotify" hint="to see your playlists" />;
  if (!items) return <p className="px-2 py-3 text-[11px] text-muted-foreground/60">Loading…</p>;
  if (items.length === 0) return <EmptyState icon={Library} title="No playlists" />;
  return (
    // F9 — bottom fade mask on the scrollable list
    <div
      className="h-full overflow-auto pr-1"
      style={{
        WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
        maskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
      }}
    >
      <ul className="space-y-0.5">
        {items.map((p) => (
          <li key={p.id}>
            <button
              onClick={() => onPlay(p.uri)}
              // F10 — density-aware row padding
              className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-foreground/5 text-left [body.density-compact_&]:py-0.5"
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
                {/* D7 — locale-format track_count */}
                <p className="truncate text-[10px] text-muted-foreground/60">
                  {p.owner ? `${p.owner} • ` : ""}{p.track_count.toLocaleString()} tracks
                </p>
              </div>
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
  if (!webOk) return <EmptyState icon={Search} title="Connect Spotify" hint="to search" />;
  return (
    <div className="h-full flex flex-col gap-1.5">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search songs, artists, albums…"
          className="w-full rounded-md bg-foreground/5 border border-foreground/10 px-2 py-1 text-xs placeholder:text-muted-foreground/50 focus:outline-none focus:border-[#1DB954]/60"
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
          <p className="px-2 py-3 text-[11px] text-muted-foreground/60">Type to search Spotify</p>
        ) : results === null ? (
          <p className="px-2 py-3 text-[11px] text-muted-foreground/60">…</p>
        ) : results.length === 0 ? (
          <EmptyState icon={Search} title="No results" />
        ) : (
          <ul className="space-y-0.5">
            {results.map((t, i) => (
              <li key={(t.uri ?? "") + i}>
                <button
                  onClick={() => t.uri && onPlay(t.uri)}
                  className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-foreground/5 text-left"
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
  if (!webOk) return <EmptyState icon={ListMusic} title="Connect Spotify" hint="to see upcoming tracks" />;
  if (!items) return <p className="px-2 py-3 text-[11px] text-muted-foreground/60">Loading…</p>;
  if (items.length === 0)
    return <EmptyState icon={ListMusic} title="Queue is empty" hint="Play something to fill it" />;
  return (
    // F9 — bottom fade mask on the scrollable list
    <div
      className="h-full overflow-auto pr-1"
      style={{
        WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
        maskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)",
      }}
    >
      <ul className="space-y-0.5">
        {/* D5 — use stable uri as key instead of array index */}
        {items.map((t, i) => (
          <li key={(t.uri ?? "") + i}>
            <button
              onClick={() => t.uri && onPlay(t.uri)}
              // F10 — density-aware row padding
              className="w-full flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-foreground/5 text-left [body.density-compact_&]:py-0.5"
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
      <CardTitle className="flex items-center gap-2 text-[13px] font-semibold tracking-[-0.02em] text-muted-foreground">
        <svg className="h-4 w-4 text-[#1DB954]" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
        </svg>
        Spotify
        {/* F6 — live dot uses --status-live token instead of bg-emerald-* */}
        {live && (
          <span
            className="h-1.5 w-1.5 rounded-full inline-block ml-1"
            style={{ background: "var(--status-live)" }}
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
      // F10 — compact density reduces vertical padding on tabs
      className={`px-2 py-0.5 text-[10px] transition-colors whitespace-nowrap [body.density-compact_&]:py-px ${
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
      : "shrink-0 h-8 w-8 rounded-full bg-foreground/10 hover:bg-foreground/15 flex items-center justify-center transition-colors";
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
