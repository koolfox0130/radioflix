"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

type Program = {
  id: string;
  title: string;
  network?: string;
  category?: string;
  raw_name?: string;
  thumbnail_url?: string;
  weekday?: string | null;
  weekday_index?: number | null;
  start_time?: string | null;
  display_start_time?: string | null;
  schedule_sort_minutes?: number | null;
};

type Recommendation = Program & {
  reason?: string;
};

type RecommendationAiState = {
  status: "idle" | "loading" | "success" | "error";
  reason?: string;
  errorMessage?: string;
};

type Episode = {
  filename: string;
  title: string;
  size: number;
  updated_at: number;
  thumbnail_url?: string;
  audio_url?: string;
};

type PlaybackStatus = "未聴" | "途中" | "聴了";

type PlaybackInfo = {
  currentTime: number;
  duration: number;
  updatedAt: number;
};

type ContinueItem = {
  program: Program;
  episode: Episode;
  playbackInfo: PlaybackInfo;
  progress: number;
};

type UnreadEpisode = {
  program: Program;
  episode: Episode;
};

const favoriteProgramNames = [
  "爆笑問題カーボーイ",
  "霜降り明星ANN",
  "マヂカルラブリーANN0",
  "山里亮太の不毛な議論",
  "GURU-GURU!",
  "ヤーレンズANN0",
];

const weekdayNames = ["月", "火", "水", "木", "金", "土", "日"];

function getCurrentRadioWeekdayIndex() {
  const now = new Date();

  if (now.getHours() < 5) {
    now.setDate(now.getDate() - 1);
  }

  return (now.getDay() + 6) % 7;
}

function getDisplayTitle(program: Program) {
  return program.title
    ?.replace(/^LFR_/, "")
    .replace(/^TBS_/, "")
    .replace(/^JUNK-/, "")
    .replace(/_/g, " ")
    .trim();
}

function getApiUrl(apiBaseUrl: string, path?: string) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${apiBaseUrl}${path}`;
}

function formatFileSize(size: number) {
  if (!size || size <= 0) return "";

  const mb = size / 1024 / 1024;

  if (mb >= 1000) {
    return `${(mb / 1024).toFixed(1)}GB`;
  }

  return `${mb.toFixed(0)}MB`;
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";

  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const restSeconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(
      restSeconds
    ).padStart(2, "0")}`;
  }

  return `${minutes}:${String(restSeconds).padStart(2, "0")}`;
}

function formatUpdatedAt(updatedAt: number) {
  if (!updatedAt) return "日付不明";

  const date = new Date(updatedAt * 1000);

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}/${month}/${day}`;
}

function getEpisodeDateParts(episode: Episode) {
  const text = `${episode.filename} ${episode.title}`;

  const compactMatch = text.match(/(20\d{2})(\d{2})(\d{2})/);

  if (compactMatch) {
    return {
      year: Number(compactMatch[1]),
      month: Number(compactMatch[2]),
      day: Number(compactMatch[3]),
    };
  }

  const separatedMatch = text.match(
    /(20\d{2})[\/\-_年.](\d{1,2})[\/\-_月.](\d{1,2})/
  );

  if (separatedMatch) {
    return {
      year: Number(separatedMatch[1]),
      month: Number(separatedMatch[2]),
      day: Number(separatedMatch[3]),
    };
  }

  return null;
}

function getEpisodeStartHour(episode: Episode) {
  const text = `${episode.filename} ${episode.title}`;
  const match = text.match(/20\d{6}[_-](\d{2})(\d{2})/);

  if (!match) return null;

  const hour = Number(match[1]);

  return hour >= 0 && hour <= 23 ? hour : null;
}

function getEpisodeBroadcastDate(episode: Episode) {
  const parts = getEpisodeDateParts(episode);
  const date = parts
    ? new Date(parts.year, parts.month - 1, parts.day)
    : new Date(episode.updated_at * 1000);

  if (Number.isNaN(date.getTime())) return null;

  const recordingStartedAt = new Date(episode.updated_at * 1000);
  const startHour =
    getEpisodeStartHour(episode) ??
    (!Number.isNaN(recordingStartedAt.getTime())
      ? recordingStartedAt.getHours()
      : null);

  if (startHour !== null && startHour < 5) {
    date.setDate(date.getDate() - 1);
  }

  return date;
}

function getEpisodeDate(episode: Episode) {
  const date = getEpisodeBroadcastDate(episode);

  if (!date) return formatUpdatedAt(episode.updated_at);

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}/${month}/${day}`;
}

function getEpisodeWeekday(episode: Episode) {
  const date = getEpisodeBroadcastDate(episode);

  if (!date) return "";

  const weekdays = ["日", "月", "火", "水", "木", "金", "土"];

  return `${weekdays[date.getDay()]}曜`;
}

function getEpisodeDisplayTitle(episode: Episode) {
  return episode.title
    .replace(/_/g, " ")
    .replace(/\.m4a$/i, "")
    .replace(/\.mp3$/i, "")
    .replace(/\.aac$/i, "")
    .replace(/\.wav$/i, "")
    .trim();
}

function getPlaybackStorageKey(program: Program, episode: Episode) {
  return `radioflix-position:${program.id}:${episode.filename}`;
}

function getSavedPlaybackInfo(
  program: Program | null,
  episode: Episode
): PlaybackInfo | null {
  if (!program) return null;
  if (typeof window === "undefined") return null;

  const key = getPlaybackStorageKey(program, episode);
  const rawValue = window.localStorage.getItem(key);

  if (!rawValue) return null;

  try {
    const parsed = JSON.parse(rawValue);

    return {
      currentTime: Number(parsed.currentTime ?? 0),
      duration: Number(parsed.duration ?? 0),
      updatedAt: Number(parsed.updatedAt ?? 0),
    };
  } catch {
    return null;
  }
}

function getEpisodePlaybackState(program: Program | null, episode: Episode) {
  const saved = getSavedPlaybackInfo(program, episode);

  if (!saved) {
    return {
      status: "未聴" as PlaybackStatus,
      progress: 0,
    };
  }

  const currentTime = Number.isFinite(saved.currentTime)
    ? saved.currentTime
    : 0;
  const duration = Number.isFinite(saved.duration) ? saved.duration : 0;

  if (currentTime < 5) {
    return {
      status: "未聴" as PlaybackStatus,
      progress: 0,
    };
  }

  if (duration > 0) {
    const progress = Math.min(Math.max(currentTime / duration, 0), 1);

    if (progress >= 0.95 || duration - currentTime <= 60) {
      return {
        status: "聴了" as PlaybackStatus,
        progress: 1,
      };
    }

    return {
      status: "途中" as PlaybackStatus,
      progress,
    };
  }

  return {
    status: "途中" as PlaybackStatus,
    progress: 0.05,
  };
}

function getStatusBadgeClass(status: PlaybackStatus) {
  if (status === "聴了") {
    return "bg-zinc-700 px-3 py-1 text-xs font-bold text-zinc-300";
  }

  if (status === "途中") {
    return "bg-amber-500/15 px-3 py-1 text-xs font-bold text-amber-300";
  }

  return "bg-emerald-500/15 px-3 py-1 text-xs font-bold text-emerald-300";
}

function ProgramImage({
  apiBaseUrl,
  program,
  size = "large",
}: {
  apiBaseUrl: string;
  program: Program;
  size?: "small" | "large" | "hero";
}) {
  const [hasError, setHasError] = useState(false);
  const imageUrl = getApiUrl(apiBaseUrl, program.thumbnail_url);

  const sizeClass =
    size === "small"
      ? "h-16 w-16 rounded-2xl"
      : size === "hero"
      ? "h-48 w-full rounded-b-3xl"
      : "h-32 w-full rounded-3xl";

  if (!imageUrl || hasError) {
    return (
      <div
        className={`${sizeClass} flex items-center justify-center bg-zinc-800 text-xs font-bold text-zinc-500`}
      >
        RadioFlix
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={program.title}
      className={`${sizeClass} object-cover`}
      onError={() => setHasError(true)}
    />
  );
}

function EpisodeImage({
  apiBaseUrl,
  episode,
}: {
  apiBaseUrl: string;
  episode: Episode;
}) {
  const [hasError, setHasError] = useState(false);
  const imageUrl = getApiUrl(apiBaseUrl, episode.thumbnail_url);

  if (!imageUrl || hasError) {
    return (
      <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-zinc-700 text-xs font-bold text-zinc-400">
        Radio
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={episode.title}
      className="h-20 w-20 shrink-0 rounded-2xl object-cover"
      onError={() => setHasError(true)}
    />
  );
}

function ScrollingTitle({ text }: { text: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLSpanElement | null>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useEffect(() => {
    function checkOverflow() {
      if (!containerRef.current || !contentRef.current) return;

      setIsOverflowing(
        contentRef.current.scrollWidth > containerRef.current.clientWidth
      );
    }

    checkOverflow();

    const timeoutId = window.setTimeout(checkOverflow, 100);
    window.addEventListener("resize", checkOverflow);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", checkOverflow);
    };
  }, [text]);

  if (!isOverflowing) {
    return (
      <div
        ref={containerRef}
        className="w-full overflow-hidden whitespace-nowrap text-lg font-bold leading-tight text-zinc-100"
      >
        <span ref={contentRef} className="block truncate">
          {text}
        </span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full overflow-hidden whitespace-nowrap text-lg font-bold leading-tight text-zinc-100"
    >
      <div key={text} className="radioflix-marquee-track">
        <span ref={contentRef} className="inline-block pr-12">
          {text}
        </span>
        <span className="inline-block pr-12">{text}</span>
      </div>
    </div>
  );
}

function GlobalStyles() {
  return (
    <style jsx global>{`
      @keyframes radioflix-marquee {
        0% {
          transform: translateX(0);
        }
        100% {
          transform: translateX(-50%);
        }
      }

      .radioflix-marquee-track {
        display: inline-flex;
        min-width: max-content;
        white-space: nowrap;
        animation-name: radioflix-marquee;
        animation-duration: 18s;
        animation-timing-function: linear;
        animation-iteration-count: infinite;
        animation-delay: 2s;
      }
    `}</style>
  );
}

function HomeContent() {
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [programs, setPrograms] = useState<Program[]>([]);
  const [selectedProgram, setSelectedProgram] = useState<Program | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null);
  const [continueItem, setContinueItem] = useState<ContinueItem | null>(null);
  const [continueLoading, setContinueLoading] = useState(false);
  const [unreadEpisodes, setUnreadEpisodes] = useState<UnreadEpisode[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [recommendationAiStates, setRecommendationAiStates] = useState<
    Record<string, RecommendationAiState>
  >({});
  const [homeView, setHomeView] = useState<"latest" | "weekday">("latest");
  const [selectedWeekday, setSelectedWeekday] = useState(
    getCurrentRadioWeekdayIndex
  );

  const [loading, setLoading] = useState(true);
  const [episodesLoading, setEpisodesLoading] = useState(false);
  const [error, setError] = useState("");
  const [episodesError, setEpisodesError] = useState("");

  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [playbackError, setPlaybackError] = useState("");
  const [autoOpenQueryHandled, setAutoOpenQueryHandled] = useState(false);

  const apiBaseUrl = "";
  const searchParams = useSearchParams();

  useEffect(() => {
    if (autoOpenQueryHandled || programs.length === 0) return;

    const programId = searchParams.get("programId");
    const episodeFilename = searchParams.get("episodeFilename");
    const autoPlay = searchParams.get("autoPlay") === "1";

    if (!programId || !episodeFilename) return;

    const targetProgram = programs.find((program) => program.id === programId);

    if (!targetProgram) return;

    openProgram(targetProgram, {
      episodeFilename,
      autoPlay,
    });

    setAutoOpenQueryHandled(true);
  }, [programs, searchParams, autoOpenQueryHandled]);

  useEffect(() => {
    const savedRate = window.localStorage.getItem("radioflix-playback-rate");

    if (savedRate === "1.2") {
      setPlaybackRate(1.2);
    }
  }, []);

  useEffect(() => {
    const audio = audioRef.current;

    if (!audio) return;

    audio.playbackRate = playbackRate;
    window.localStorage.setItem("radioflix-playback-rate", String(playbackRate));
  }, [playbackRate]);

  useEffect(() => {
    async function loadPrograms() {
      try {
        const response = await fetch(`${apiBaseUrl}/programs`);

        if (!response.ok) {
          throw new Error("番組一覧を取得できませんでした");
        }

        const data = await response.json();
        setPrograms(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error(err);
        setError("NASの録音一覧を取得できませんでした");
      } finally {
        setLoading(false);
      }
    }

    loadPrograms();
  }, [apiBaseUrl]);

  useEffect(() => {
    let cancelled = false;

    async function loadRecommendations() {
      try {
        const response = await fetch(`${apiBaseUrl}/api/recommendations`);

        if (!response.ok) return;

        const data = await response.json();

        if (!cancelled) {
          setRecommendations(Array.isArray(data) ? (data as Recommendation[]) : []);
        }
      } catch {
        // Recommendations are optional and should not affect the main page.
      }
    }

    loadRecommendations();

    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  async function generateRecommendationReason(recommendation: Recommendation) {
    const currentState = recommendationAiStates[recommendation.id];

    if (currentState?.status === "loading") return;

    setRecommendationAiStates((currentStates) => ({
      ...currentStates,
      [recommendation.id]: { status: "loading" },
    }));

    try {
      const response = await fetch(`${apiBaseUrl}/api/ai/recommendation-reason`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: recommendation.title,
          network: recommendation.network ?? "",
          existing_reason: recommendation.reason ?? "",
          favorite_titles: favoriteProgramNames,
        }),
      });

      let data: { reason?: string; error?: string } = {};

      try {
        data = await response.json();
      } catch {
        data = {};
      }

      if (!response.ok || !data.reason) {
        const unavailable =
          response.status === 503 ||
          [
            "memory_insufficient",
            "swap_insufficient",
            "disabled",
            "unreachable",
            "timeout",
          ].includes(data.error ?? "");

        throw new Error(
          unavailable
            ? "今はAI理由を生成できません"
            : "AI理由の生成に失敗しました"
        );
      }

      setRecommendationAiStates((currentStates) => ({
        ...currentStates,
        [recommendation.id]: { status: "success", reason: data.reason },
      }));
    } catch (error) {
      setRecommendationAiStates((currentStates) => ({
        ...currentStates,
        [recommendation.id]: {
          status: "error",
          errorMessage:
            error instanceof Error
              ? error.message
              : "AI理由の生成に失敗しました",
        },
      }));
    }
  }

  useEffect(() => {
    if (!audioRef.current || !selectedEpisode) return;

    audioRef.current.load();
  }, [selectedEpisode]);

  useEffect(() => {
    if (programs.length === 0) return;

    let cancelled = false;

    async function loadContinueItem() {
      setContinueLoading(true);

      try {
        const allEpisodeGroups = await Promise.all(
          programs.map(async (program) => {
            try {
              const response = await fetch(
                `${apiBaseUrl}/programs/${program.id}/episodes`
              );

              if (!response.ok) {
                return {
                  program,
                  episodes: [] as Episode[],
                };
              }

              const data = await response.json();

              return {
                program,
                episodes: Array.isArray(data) ? (data as Episode[]) : [],
              };
            } catch {
              return {
                program,
                episodes: [] as Episode[],
              };
            }
          })
        );

        const candidates: ContinueItem[] = [];
        const unreadCandidates: UnreadEpisode[] = [];

        for (const group of allEpisodeGroups) {
          for (const episode of group.episodes) {
            const playbackInfo = getSavedPlaybackInfo(group.program, episode);
            const playbackState = getEpisodePlaybackState(
              group.program,
              episode
            );

            if (playbackState.status === "未聴") {
              unreadCandidates.push({
                program: group.program,
                episode,
              });
            }

            if (!playbackInfo) continue;
            if (playbackState.status !== "途中") continue;

            candidates.push({
              program: group.program,
              episode,
              playbackInfo,
              progress: playbackState.progress,
            });
          }
        }

        candidates.sort(
          (a, b) => b.playbackInfo.updatedAt - a.playbackInfo.updatedAt
        );
        unreadCandidates.sort(
          (a, b) => b.episode.updated_at - a.episode.updated_at
        );

        if (!cancelled) {
          setContinueItem(candidates[0] ?? null);
          setUnreadEpisodes(unreadCandidates);
        }
      } finally {
        if (!cancelled) {
          setContinueLoading(false);
        }
      }
    }

    loadContinueItem();

    return () => {
      cancelled = true;
    };
  }, [programs, apiBaseUrl]);

  const favoritePrograms = useMemo(() => {
    return favoriteProgramNames
      .map((favoriteName) =>
        programs.find((program) => program.title.includes(favoriteName))
      )
      .filter((program): program is Program => Boolean(program));
  }, [programs]);

  const otherPrograms = useMemo(() => {
    return programs.filter(
      (program) =>
        !favoritePrograms.some((favorite) => favorite.id === program.id)
    );
  }, [programs, favoritePrograms]);

  const weekdayPrograms = useMemo(() => {
    return programs
      .filter((program) => program.weekday_index === selectedWeekday)
      .sort(
        (a, b) =>
          (a.schedule_sort_minutes ?? Number.MAX_SAFE_INTEGER) -
          (b.schedule_sort_minutes ?? Number.MAX_SAFE_INTEGER)
      );
  }, [programs, selectedWeekday]);

  function getPlaybackKey(episode: Episode) {
    if (!selectedProgram) return "";
    return getPlaybackStorageKey(selectedProgram, episode);
  }

  function savePlaybackPosition(
    episode: Episode,
    nextCurrentTime: number,
    nextDuration: number
  ) {
    const playbackKey = getPlaybackKey(episode);

    if (!playbackKey || !selectedProgram) return;

    const nextPlaybackInfo = {
      currentTime: nextCurrentTime,
      duration: nextDuration,
      updatedAt: Date.now(),
    };

    window.localStorage.setItem(playbackKey, JSON.stringify(nextPlaybackInfo));

    const playbackState = getEpisodePlaybackState(selectedProgram, episode);

    setUnreadEpisodes((currentUnreadEpisodes) => {
      const currentIndex = currentUnreadEpisodes.findIndex(
        (item) =>
          item.program.id === selectedProgram.id &&
          item.episode.filename === episode.filename
      );

      if (playbackState.status === "未聴") {
        if (currentIndex >= 0) return currentUnreadEpisodes;

        return [
          ...currentUnreadEpisodes,
          { program: selectedProgram, episode },
        ].sort((a, b) => b.episode.updated_at - a.episode.updated_at);
      }

      if (currentIndex < 0) return currentUnreadEpisodes;

      return currentUnreadEpisodes.filter((_, index) => index !== currentIndex);
    });

    if (playbackState.status === "途中") {
      setContinueItem({
        program: selectedProgram,
        episode,
        playbackInfo: nextPlaybackInfo,
        progress: playbackState.progress,
      });
    }
  }

  async function openProgram(
    program: Program,
    options?: {
      episodeFilename?: string;
      autoPlay?: boolean;
    }
  ) {
    setSelectedProgram(program);
    setEpisodes([]);
    setSelectedEpisode(null);
    setEpisodesError("");
    setEpisodesLoading(true);
    setIsPlaying(false);
    setDuration(0);
    setCurrentTime(0);
    setPlaybackError("");

    try {
      const response = await fetch(
        `${apiBaseUrl}/programs/${program.id}/episodes`
      );

      if (!response.ok) {
        throw new Error("録音一覧を取得できませんでした");
      }

      const data = await response.json();
      const nextEpisodes = Array.isArray(data) ? (data as Episode[]) : [];

      setEpisodes(nextEpisodes);

      if (options?.episodeFilename) {
        const targetEpisode = nextEpisodes.find(
          (episode) => episode.filename === options.episodeFilename
        );

        if (targetEpisode) {
          setSelectedEpisode(targetEpisode);
          setShouldAutoPlay(options.autoPlay ?? true);
        }
      }
    } catch (err) {
      console.error(err);
      setEpisodesError("この番組の録音一覧を取得できませんでした");
    } finally {
      setEpisodesLoading(false);
    }
  }

  function openContinueItem() {
    if (!continueItem) return;

    openProgram(continueItem.program, {
      episodeFilename: continueItem.episode.filename,
      autoPlay: true,
    });
  }

  function closeProgram() {
    if (audioRef.current) {
      audioRef.current.pause();
    }

    setSelectedProgram(null);
    setEpisodes([]);
    setSelectedEpisode(null);
    setEpisodesError("");
    setIsPlaying(false);
    setDuration(0);
    setCurrentTime(0);
    setPlaybackError("");
  }

  function selectEpisode(episode: Episode, autoPlay = true) {
    setSelectedEpisode(episode);
    setShouldAutoPlay(autoPlay);
    setCurrentTime(0);
    setDuration(0);
    setPlaybackError("");
  }

  async function togglePlay() {
    const audio = audioRef.current;

    if (!audio || !selectedEpisode) return;

    if (audio.paused) {
      try {
        audio.playbackRate = playbackRate;
        await audio.play();
        setIsPlaying(true);
        setPlaybackError("");
      } catch (err) {
        console.error("音声の再生に失敗しました", err);
        setIsPlaying(false);
        setPlaybackError(
          "音声を再生できませんでした。通信状況を確認して、もう一度お試しください。"
        );
      }
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  }

  function togglePlaybackRate() {
    const nextRate = playbackRate === 1 ? 1.2 : 1;

    setPlaybackRate(nextRate);

    const audio = audioRef.current;

    if (audio) {
      audio.playbackRate = nextRate;
    }
  }

  function skip(seconds: number) {
    const audio = audioRef.current;

    if (
      !audio ||
      !selectedEpisode ||
      audio.readyState === HTMLMediaElement.HAVE_NOTHING ||
      !Number.isFinite(audio.currentTime)
    ) {
      return;
    }

    const audioDuration = audio.duration;
    const hasValidDuration =
      Number.isFinite(audioDuration) && audioDuration > 0;
    const unclampedTime = Math.max(audio.currentTime + seconds, 0);
    const nextTime = hasValidDuration
      ? Math.min(unclampedTime, audioDuration)
      : unclampedTime;

    try {
      audio.currentTime = nextTime;
    } catch (err) {
      console.error("音声の再生位置を変更できませんでした", err);
      return;
    }

    setCurrentTime(nextTime);

    savePlaybackPosition(
      selectedEpisode,
      nextTime,
      hasValidDuration ? audioDuration : 0
    );
  }

  function seek(seconds: number) {
    const audio = audioRef.current;

    if (!audio) return;

    audio.currentTime = seconds;
    setCurrentTime(seconds);

    if (selectedEpisode) {
      savePlaybackPosition(selectedEpisode, seconds, audio.duration || 0);
    }
  }

  function selectAdjacentEpisode(direction: "older" | "newer") {
    if (!selectedEpisode) return;

    const currentIndex = episodes.findIndex(
      (episode) => episode.filename === selectedEpisode.filename
    );

    if (currentIndex < 0) return;

    const nextIndex =
      direction === "older" ? currentIndex + 1 : currentIndex - 1;

    if (nextIndex < 0 || nextIndex >= episodes.length) return;

    selectEpisode(episodes[nextIndex], true);
  }

  function handleLoadedMetadata() {
    const audio = audioRef.current;

    if (!audio || !selectedEpisode) return;

    audio.playbackRate = playbackRate;

    const nextDuration = audio.duration || 0;
    setDuration(nextDuration);

    const playbackKey = getPlaybackKey(selectedEpisode);
    const savedPositionText = playbackKey
      ? window.localStorage.getItem(playbackKey)
      : null;

    if (savedPositionText) {
      try {
        const savedPosition = JSON.parse(savedPositionText);
        const savedTime = Number(savedPosition.currentTime ?? 0);

        if (
          Number.isFinite(savedTime) &&
          savedTime > 5 &&
          savedTime < nextDuration - 10
        ) {
          audio.currentTime = savedTime;
          setCurrentTime(savedTime);
        }
      } catch {
        // 保存データが壊れていた場合は無視
      }
    }

    if (shouldAutoPlay) {
      audio
        .play()
        .then(() => {
          setIsPlaying(true);
          setPlaybackError("");
        })
        .catch((err) => {
          console.error("音声の自動再生に失敗しました", err);
          setIsPlaying(false);
          setPlaybackError(
            "音声を再生できませんでした。再生ボタンをもう一度押してください。"
          );
        });
    }
  }

  function handleAudioError() {
    const mediaError = audioRef.current?.error;

    console.error("音声ファイルの読み込みに失敗しました", mediaError);
    setIsPlaying(false);
    setPlaybackError(
      "音声ファイルを読み込めませんでした。別の録音を選ぶか、通信状況を確認してください。"
    );
  }

  function handleTimeUpdate() {
    const audio = audioRef.current;

    if (!audio || !selectedEpisode) return;

    const nextCurrentTime = audio.currentTime || 0;
    const nextDuration = audio.duration || 0;

    setCurrentTime(nextCurrentTime);
    setDuration(nextDuration);

    savePlaybackPosition(selectedEpisode, nextCurrentTime, nextDuration);
  }

  function handleEnded() {
    const audio = audioRef.current;

    setIsPlaying(false);

    if (!audio || !selectedEpisode) return;

    const nextDuration = audio.duration || duration || 0;

    setCurrentTime(nextDuration);
    savePlaybackPosition(selectedEpisode, nextDuration, nextDuration);
  }

  const selectedEpisodeAudioUrl = selectedEpisode
    ? getApiUrl(apiBaseUrl, selectedEpisode.audio_url)
    : "";

  const selectedEpisodeIndex = selectedEpisode
    ? episodes.findIndex(
        (episode) => episode.filename === selectedEpisode.filename
      )
    : -1;

  const hasOlderEpisode =
    selectedEpisodeIndex >= 0 && selectedEpisodeIndex < episodes.length - 1;

  const hasNewerEpisode = selectedEpisodeIndex > 0;

  if (selectedProgram) {
    return (
      <>
        <GlobalStyles />

        <main className="min-h-screen bg-zinc-950 text-zinc-100">
          <div className="mx-auto max-w-md pb-72">
            <div className="relative">
              <ProgramImage
                apiBaseUrl={apiBaseUrl}
                program={selectedProgram}
                size="hero"
              />

              <button
                onClick={closeProgram}
                className="absolute left-4 top-4 rounded-full bg-black/60 px-4 py-2 text-sm font-bold text-white backdrop-blur"
              >
                ← 戻る
              </button>
            </div>

            <div className="px-4 pt-5">
              <p className="text-sm text-zinc-400">
                {selectedProgram.network ?? "RadioFlix"} /{" "}
                {selectedProgram.category ?? "録音番組"}
              </p>

              <h1 className="mt-2 text-3xl font-bold tracking-tight">
                {getDisplayTitle(selectedProgram)}
              </h1>

              <div className="mt-5 rounded-3xl bg-zinc-900 p-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold">録音一覧</h2>
                  <span className="text-xs text-zinc-500">
                    {episodes.length}件
                  </span>
                </div>

                {episodesLoading && (
                  <p className="mt-4 text-sm text-zinc-400">
                    録音一覧を読み込み中...
                  </p>
                )}

                {episodesError && (
                  <p className="mt-4 rounded-2xl border border-red-500/40 bg-red-950/40 p-4 text-sm text-red-200">
                    {episodesError}
                  </p>
                )}

                {!episodesLoading &&
                  !episodesError &&
                  episodes.length === 0 && (
                    <p className="mt-4 text-sm text-zinc-400">
                      この番組の録音ファイルが見つかりませんでした。
                    </p>
                  )}

                {!episodesLoading &&
                  !episodesError &&
                  episodes.length > 0 && (
                    <div className="mt-4 space-y-3">
                      {episodes.map((episode) => {
                        const isSelected =
                          selectedEpisode?.filename === episode.filename;

                        const playbackState = getEpisodePlaybackState(
                          selectedProgram,
                          episode
                        );

                        const progressPercent = Math.round(
                          playbackState.progress * 100
                        );

                        return (
                          <button
                            key={episode.filename}
                            onClick={() => selectEpisode(episode, true)}
                            className={`w-full rounded-2xl p-3 text-left transition active:scale-[0.99] ${
                              isSelected
                                ? "bg-zinc-700 ring-2 ring-zinc-400"
                                : "bg-zinc-800"
                            }`}
                          >
                            <div className="flex items-center gap-3">
                              <EpisodeImage
                                apiBaseUrl={apiBaseUrl}
                                episode={episode}
                              />

                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <p className="text-xs text-zinc-500">
                                    {getEpisodeDate(episode)}
                                  </p>

                                  {getEpisodeWeekday(episode) && (
                                    <span className="rounded-full bg-zinc-700 px-2 py-0.5 text-xs font-bold text-zinc-300">
                                      {getEpisodeWeekday(episode)}
                                    </span>
                                  )}
                                </div>

                                <h3 className="mt-1 line-clamp-2 font-bold">
                                  {getEpisodeDisplayTitle(episode)}
                                </h3>

                                <p className="mt-2 text-xs text-zinc-500">
                                  {formatFileSize(episode.size)}
                                </p>

                                {playbackState.status !== "未聴" && (
                                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-700">
                                    <div
                                      className={`h-full rounded-full ${
                                        playbackState.status === "聴了"
                                          ? "bg-zinc-400"
                                          : "bg-amber-300"
                                      }`}
                                      style={{
                                        width: `${progressPercent}%`,
                                      }}
                                    />
                                  </div>
                                )}
                              </div>

                              <span
                                className={`shrink-0 rounded-full ${getStatusBadgeClass(
                                  playbackState.status
                                )}`}
                              >
                                {playbackState.status}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
              </div>
            </div>
          </div>

          <audio
            ref={audioRef}
            src={selectedEpisodeAudioUrl || undefined}
            preload="metadata"
            onLoadedMetadata={handleLoadedMetadata}
            onTimeUpdate={handleTimeUpdate}
            onPlay={() => {
              setIsPlaying(true);
              setPlaybackError("");
            }}
            onPause={() => setIsPlaying(false)}
            onEnded={handleEnded}
            onError={handleAudioError}
          />

          {selectedEpisode && (
            <div className="fixed bottom-14 left-0 right-0 z-40 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur">
              <div className="mx-auto max-w-md px-4 py-3">
                <div className="mb-3 flex items-start gap-3">
                  <EpisodeImage
                    apiBaseUrl={apiBaseUrl}
                    episode={selectedEpisode}
                  />

                  <div className="min-w-0 flex-1">
                    <p className="mb-1 text-xs text-zinc-500">
                      {getEpisodeDate(selectedEpisode)}{" "}
                      {getEpisodeWeekday(selectedEpisode)}
                    </p>

                    <ScrollingTitle
                      text={getEpisodeDisplayTitle(selectedEpisode)}
                    />

                    <div className="mt-2 flex items-center justify-between gap-3">
                      <p className="text-xs text-zinc-500">
                        {formatTime(currentTime)} / {formatTime(duration)}
                      </p>

                      <button
                        onClick={togglePlaybackRate}
                        className="shrink-0 rounded-2xl bg-zinc-800 px-4 py-2 text-sm font-bold text-zinc-100 active:scale-95"
                        title="再生速度を切り替え"
                      >
                        {playbackRate.toFixed(1)}x
                      </button>
                    </div>
                  </div>
                </div>

                {playbackError && (
                  <p
                    role="alert"
                    className="mb-3 rounded-xl border border-red-500/40 bg-red-950/50 px-3 py-2 text-xs text-red-200"
                  >
                    {playbackError}
                  </p>
                )}

                <input
                  type="range"
                  min={0}
                  max={duration || 0}
                  value={Math.min(currentTime, duration || currentTime)}
                  onChange={(event) => seek(Number(event.target.value))}
                  className="mb-3 w-full"
                />

                <div className="grid grid-cols-5 items-center gap-2 text-sm">
                  <button
                    onClick={() => selectAdjacentEpisode("older")}
                    disabled={!hasOlderEpisode}
                    className="rounded-2xl bg-zinc-800 px-2 py-3 font-bold disabled:opacity-30"
                  >
                    ⏮
                  </button>

                  <button
                    onClick={() => skip(-15)}
                    className="rounded-2xl bg-zinc-800 px-2 py-3 font-bold"
                  >
                    ↩15
                  </button>

                  <button
                    onClick={togglePlay}
                    className="rounded-2xl bg-zinc-100 px-2 py-3 text-lg font-bold text-zinc-950"
                  >
                    {isPlaying ? "⏸" : "▶"}
                  </button>

                  <button
                    onClick={() => skip(30)}
                    className="rounded-2xl bg-zinc-800 px-2 py-3 font-bold"
                  >
                    30↪
                  </button>

                  <button
                    onClick={() => selectAdjacentEpisode("newer")}
                    disabled={!hasNewerEpisode}
                    className="rounded-2xl bg-zinc-800 px-2 py-3 font-bold disabled:opacity-30"
                  >
                    ⏭
                  </button>
                </div>

                <div className="mt-2 grid grid-cols-5 text-center text-[10px] text-zinc-500">
                  <span>前の録音</span>
                  <span>15秒戻る</span>
                  <span>再生</span>
                  <span>30秒送る</span>
                  <span>次の録音</span>
                </div>
              </div>
            </div>
          )}

          <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur">
            <div className="mx-auto grid max-w-md grid-cols-4 px-2 py-2 text-center text-xs text-zinc-400">
              <button
                onClick={closeProgram}
                className="rounded-2xl px-2 py-2 font-bold text-zinc-100"
              >
                ホーム
              </button>
              <button className="rounded-2xl px-2 py-2">番組</button>
              <Link href="/unread" className="rounded-2xl px-2 py-2">
                未聴
              </Link>
              <button className="rounded-2xl px-2 py-2">検索</button>
            </div>
          </nav>
        </main>
      </>
    );
  }

  return (
    <>
      <GlobalStyles />

      <main className="min-h-screen bg-zinc-950 text-zinc-100">
        <div className="mx-auto max-w-md px-4 pb-24 pt-6">
          <header className="mb-6">
            {/* Project kool-AI pipeline test */}
            <p className="text-sm text-zinc-400">NAS録音ラジオ</p>
            <h1 className="text-3xl font-bold tracking-tight">
              <Link href="/">RadioFlix</Link>
            </h1>
            <p className="mt-2 text-sm text-zinc-400">
              番組を選んで、録音一覧を開きます。
            </p>
          </header>

          <div className="mb-6 grid grid-cols-2 rounded-2xl bg-zinc-900 p-1">
            <button
              type="button"
              onClick={() => setHomeView("latest")}
              className={`min-h-11 rounded-xl px-4 py-2 text-sm font-bold transition ${
                homeView === "latest"
                  ? "bg-zinc-100 text-zinc-950"
                  : "text-zinc-400"
              }`}
              aria-pressed={homeView === "latest"}
            >
              最新
            </button>
            <button
              type="button"
              onClick={() => setHomeView("weekday")}
              className={`min-h-11 rounded-xl px-4 py-2 text-sm font-bold transition ${
                homeView === "weekday"
                  ? "bg-zinc-100 text-zinc-950"
                  : "text-zinc-400"
              }`}
              aria-pressed={homeView === "weekday"}
            >
              曜日別
            </button>
          </div>

          {loading && (
            <div className="rounded-3xl bg-zinc-900 p-5 text-sm text-zinc-400">
              録音一覧を読み込み中...
            </div>
          )}

          {error && (
            <div className="rounded-3xl border border-red-500/40 bg-red-950/40 p-5 text-sm text-red-200">
              {error}
            </div>
          )}

          {!loading && !error && (
            <>
              <div className={homeView === "latest" ? "" : "hidden"}>
              {continueItem && (
                <section className="mb-8">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-lg font-bold">続きから聴く</h2>
                    <span className="text-xs text-zinc-500">
                      前回の続き
                    </span>
                  </div>

                  <button
                    onClick={openContinueItem}
                    className="w-full overflow-hidden rounded-3xl bg-zinc-900 text-left shadow-lg transition active:scale-[0.99]"
                  >
                    <EpisodeImage
                      apiBaseUrl={apiBaseUrl}
                      episode={continueItem.episode}
                    />

                    <div className="p-5">
                      <p className="text-xs text-zinc-500">
                        {getDisplayTitle(continueItem.program)} /{" "}
                        {getEpisodeDate(continueItem.episode)}{" "}
                        {getEpisodeWeekday(continueItem.episode)}
                      </p>

                      <h3 className="mt-2 line-clamp-2 text-xl font-bold">
                        {getEpisodeDisplayTitle(continueItem.episode)}
                      </h3>

                      <p className="mt-2 text-sm text-zinc-400">
                        {formatTime(continueItem.playbackInfo.currentTime)} /{" "}
                        {formatTime(continueItem.playbackInfo.duration)}
                      </p>

                      <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-700">
                        <div
                          className="h-full rounded-full bg-amber-300"
                          style={{
                            width: `${Math.round(
                              continueItem.progress * 100
                            )}%`,
                          }}
                        />
                      </div>

                      <div className="mt-5 rounded-2xl bg-zinc-100 px-4 py-3 text-center font-bold text-zinc-950">
                        ▶ 続きから再生
                      </div>
                    </div>
                  </button>
                </section>
              )}

              {!continueItem && continueLoading && (
                <section className="mb-8">
                  <div className="rounded-3xl bg-zinc-900 p-5 text-sm text-zinc-400">
                    続きから聴く録音を確認中...
                  </div>
                </section>
              )}

              {favoritePrograms.length > 0 && (
                <section className="mb-8">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-lg font-bold">お気に入り番組</h2>
                    <span className="text-xs text-zinc-500">
                      {favoritePrograms.length}件
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    {favoritePrograms.map((program) => (
                      <button
                        key={program.id}
                        onClick={() => openProgram(program)}
                        className="overflow-hidden rounded-3xl bg-zinc-900 text-left transition active:scale-[0.99]"
                      >
                        <ProgramImage
                          apiBaseUrl={apiBaseUrl}
                          program={program}
                          size="large"
                        />

                        <div className="p-3">
                          <p className="text-xs text-zinc-500">
                            {program.category ?? program.network ?? "録音"}
                          </p>
                          <h3 className="mt-1 line-clamp-2 font-bold">
                            {getDisplayTitle(program)}
                          </h3>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {unreadEpisodes.length > 0 && (
                <section className="mb-8">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-lg font-bold">
                      未聴エピソード（{unreadEpisodes.length}件）
                    </h2>
                  </div>

                  <div className="space-y-3">
                    {unreadEpisodes.map((item) => (
                      <button
                        key={`${item.program.id}:${item.episode.filename}`}
                        onClick={() =>
                          openProgram(item.program, {
                            episodeFilename: item.episode.filename,
                            autoPlay: true,
                          })
                        }
                        className="w-full rounded-3xl bg-zinc-900 p-3 text-left transition active:scale-[0.99]"
                      >
                        <div className="flex items-center gap-4">
                          <ProgramImage
                            apiBaseUrl={apiBaseUrl}
                            program={item.program}
                            size="small"
                          />

                          <div className="min-w-0 flex-1">
                            <h3 className="truncate font-bold">
                              {getDisplayTitle(item.program)}
                            </h3>
                            <p className="mt-1 text-xs text-zinc-500">
                              {getEpisodeDate(item.episode)}{" "}
                              {getEpisodeWeekday(item.episode)}
                            </p>
                            <p className="mt-1 line-clamp-2 text-sm text-zinc-400">
                              {getEpisodeDisplayTitle(item.episode)}
                            </p>
                          </div>

                          <span className="shrink-0 text-zinc-500">›</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <section className="mb-8">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-lg font-bold">番組一覧</h2>
                  <span className="text-xs text-zinc-500">
                    {programs.length}件
                  </span>
                </div>

                <div className="space-y-3">
                  {otherPrograms.map((program) => (
                    <button
                      key={program.id}
                      onClick={() => openProgram(program)}
                      className="w-full rounded-3xl bg-zinc-900 p-3 text-left transition active:scale-[0.99]"
                    >
                      <div className="flex items-center gap-4">
                        <ProgramImage
                          apiBaseUrl={apiBaseUrl}
                          program={program}
                          size="small"
                        />

                        <div className="min-w-0 flex-1">
                          <p className="text-xs text-zinc-500">
                            {program.category ?? program.network ?? "録音"}
                          </p>
                          <h3 className="mt-1 truncate font-bold">
                            {getDisplayTitle(program)}
                          </h3>
                          <p className="mt-1 text-sm text-zinc-400">
                            {program.network ?? "放送局不明"}
                          </p>
                        </div>

                        <span className="shrink-0 text-zinc-500">›</span>
                      </div>
                    </button>
                  ))}
                </div>
              </section>

              {recommendations.length > 0 && (
                <section className="mb-8">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-lg font-bold">おすすめ番組</h2>
                    <span className="text-xs text-zinc-500">
                      {recommendations.length}件
                    </span>
                  </div>

                  <div className="space-y-3">
                    {recommendations.map((recommendation) => {
                      const aiState =
                        recommendationAiStates[recommendation.id] ?? {
                          status: "idle" as const,
                        };

                      return (
                        <article
                          key={recommendation.id}
                          className="rounded-3xl bg-zinc-900 p-4"
                        >
                          <div className="flex items-start gap-3">
                            <ProgramImage
                              apiBaseUrl={apiBaseUrl}
                              program={recommendation}
                              size="small"
                            />

                            <div className="min-w-0 flex-1">
                              <p className="text-xs text-zinc-500">
                                {recommendation.network ?? "放送局不明"}
                              </p>
                              <h3 className="mt-1 font-bold">
                                {recommendation.title}
                              </h3>
                            </div>
                          </div>

                          {recommendation.reason && (
                            <p className="mt-3 text-sm text-zinc-300">
                              {recommendation.reason}
                            </p>
                          )}

                          {aiState.status === "loading" && (
                            <p className="mt-3 text-sm text-amber-200">
                              AIが考えています…
                            </p>
                          )}

                          {aiState.status === "success" && aiState.reason && (
                            <div className="mt-3 rounded-2xl bg-zinc-800 p-3">
                              <p className="text-xs font-bold text-amber-200">
                                ✨ AIおすすめ理由
                              </p>
                              <p className="mt-1 text-sm text-zinc-200">
                                {aiState.reason}
                              </p>
                            </div>
                          )}

                          {aiState.status === "error" && (
                            <p className="mt-3 text-sm text-red-200">
                              {aiState.errorMessage}
                            </p>
                          )}

                          <button
                            type="button"
                            onClick={() =>
                              generateRecommendationReason(recommendation)
                            }
                            disabled={aiState.status === "loading"}
                            className="mt-4 w-full rounded-2xl bg-zinc-100 px-4 py-3 text-sm font-bold text-zinc-950 transition active:scale-[0.99] disabled:cursor-wait disabled:opacity-50"
                          >
                            {aiState.status === "loading"
                              ? "AIが考えています…"
                              : "✨ AIに理由を聞く"}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}
              </div>

              {homeView === "weekday" && (
                <section className="mb-8">
                  <div
                    className="grid grid-cols-7 gap-1"
                    aria-label="曜日を選択"
                  >
                    {weekdayNames.map((weekday, index) => (
                      <button
                        key={weekday}
                        type="button"
                        onClick={() => setSelectedWeekday(index)}
                        className={`min-h-11 rounded-xl text-sm font-bold transition active:scale-95 ${
                          selectedWeekday === index
                            ? "bg-zinc-100 text-zinc-950"
                            : "bg-zinc-900 text-zinc-400"
                        }`}
                        aria-pressed={selectedWeekday === index}
                        aria-label={`${weekday}曜日`}
                      >
                        {weekday}
                      </button>
                    ))}
                  </div>

                  <div className="mb-3 mt-6 flex items-center justify-between">
                    <h2 className="text-xl font-bold">
                      {weekdayNames[selectedWeekday]}曜日
                    </h2>
                    <span className="text-xs text-zinc-500">
                      {weekdayPrograms.length}件
                    </span>
                  </div>

                  {weekdayPrograms.length === 0 ? (
                    <div className="rounded-3xl bg-zinc-900 p-5 text-sm text-zinc-400">
                      この曜日の番組はまだありません。
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {weekdayPrograms.map((program) => (
                        <button
                          key={program.id}
                          type="button"
                          onClick={() => openProgram(program)}
                          className="w-full rounded-3xl bg-zinc-900 p-3 text-left transition active:scale-[0.99]"
                        >
                          <div className="flex items-center gap-3">
                            <p className="w-12 shrink-0 text-center text-lg font-bold tabular-nums text-zinc-100">
                              {program.display_start_time}
                            </p>
                            <ProgramImage
                              apiBaseUrl={apiBaseUrl}
                              program={program}
                              size="small"
                            />
                            <div className="min-w-0 flex-1">
                              <h3 className="line-clamp-2 font-bold">
                                {getDisplayTitle(program)}
                              </h3>
                              <p className="mt-1 text-sm text-zinc-400">
                                {program.network || program.category || "録音番組"}
                              </p>
                            </div>
                            <span className="shrink-0 text-zinc-500">›</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </div>

        <nav className="fixed bottom-0 left-0 right-0 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur">
          <div className="mx-auto grid max-w-md grid-cols-4 px-2 py-2 text-center text-xs text-zinc-400">
            <Link href="/" className="rounded-2xl px-2 py-2 font-bold text-zinc-100">
              ホーム
            </Link>
            <button className="rounded-2xl px-2 py-2">番組</button>
            <Link href="/unread" className="rounded-2xl px-2 py-2">
              未聴
            </Link>
            <button className="rounded-2xl px-2 py-2">検索</button>
          </div>
        </nav>
      </main>
    </>
  );
}

export default function Home() {
  return (
    <Suspense fallback={null}>
      <HomeContent />
    </Suspense>
  );
}
