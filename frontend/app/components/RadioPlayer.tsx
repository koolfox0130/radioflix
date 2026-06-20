"use client";

import { useMemo, useRef, useState } from "react";

type Episode = {
  filename: string;
  title: string;
  size: number;
  updated_at: number;
};

type Props = {
  episodes: Episode[];
  programId: string;
  publicApiBaseUrl: string;
};

function formatFileSize(size: number) {
  const mb = size / 1024 / 1024;
  return `${mb.toFixed(1)} MB`;
}

function formatDate(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function createAudioUrl(
  publicApiBaseUrl: string,
  programId: string,
  filename: string
) {
  return `${publicApiBaseUrl}/audio/${encodeURIComponent(
    programId
  )}/${encodeURIComponent(filename)}`;
}

export default function RadioPlayer({
  episodes,
  programId,
  publicApiBaseUrl,
}: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);

  const currentEpisode = episodes[currentIndex];

  const audioUrl = useMemo(() => {
    if (!currentEpisode) {
      return "";
    }

    return createAudioUrl(publicApiBaseUrl, programId, currentEpisode.filename);
  }, [currentEpisode, programId, publicApiBaseUrl]);

  function skip(seconds: number) {
    const audio = audioRef.current;

    if (!audio) {
      return;
    }

    audio.currentTime = Math.max(0, audio.currentTime + seconds);
  }

  function moveEpisode(nextIndex: number) {
    if (nextIndex < 0 || nextIndex >= episodes.length) {
      return;
    }

    setCurrentIndex(nextIndex);

    setTimeout(() => {
      const audio = audioRef.current;

      if (!audio) {
        return;
      }

      audio.load();
      audio.play().catch(() => {
        // ブラウザ側の自動再生制限で失敗することがあるので握りつぶす
      });
    }, 0);
  }

  function playPreviousEpisode() {
    moveEpisode(currentIndex - 1);
  }

  function playNextEpisode() {
    moveEpisode(currentIndex + 1);
  }

  if (episodes.length === 0 || !currentEpisode) {
    return (
      <div className="bg-[#232428] border border-[#34363b] rounded-2xl p-4 text-zinc-400">
        録音データが見つかりません
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="bg-[#232428] border border-[#34363b] rounded-3xl p-5">
        <div className="text-xs text-zinc-400 mb-2">
          再生中 {currentIndex + 1} / {episodes.length}
        </div>

        <div className="text-xl font-black leading-snug break-all">
          {currentEpisode.title}
        </div>

        <div className="text-xs text-zinc-400 mt-2">
          {formatDate(currentEpisode.updated_at)} /{" "}
          {formatFileSize(currentEpisode.size)}
        </div>

        <audio
          ref={audioRef}
          controls
          preload="metadata"
          src={audioUrl}
          className="w-full mt-5"
        />

        <div className="grid grid-cols-4 gap-2 mt-5">
          <button
            type="button"
            onClick={playPreviousEpisode}
            disabled={currentIndex === 0}
            className="rounded-2xl bg-zinc-800 px-2 py-3 text-sm font-bold disabled:opacity-30"
          >
            前の録音
          </button>

          <button
            type="button"
            onClick={() => skip(-15)}
            className="rounded-2xl bg-zinc-800 px-2 py-3 text-sm font-bold"
          >
            -15秒
          </button>

          <button
            type="button"
            onClick={() => skip(30)}
            className="rounded-2xl bg-zinc-800 px-2 py-3 text-sm font-bold"
          >
            +30秒
          </button>

          <button
            type="button"
            onClick={playNextEpisode}
            disabled={currentIndex === episodes.length - 1}
            className="rounded-2xl bg-zinc-800 px-2 py-3 text-sm font-bold disabled:opacity-30"
          >
            次の録音
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {episodes.map((episode, index) => {
          const isActive = index === currentIndex;

          return (
            <button
              key={episode.filename}
              type="button"
              onClick={() => moveEpisode(index)}
              className={`w-full text-left rounded-2xl border p-4 ${
                isActive
                  ? "bg-yellow-300/10 border-yellow-300/50"
                  : "bg-[#232428] border-[#34363b]"
              }`}
            >
              <div className="text-sm font-bold leading-snug break-all">
                {episode.title}
              </div>

              <div className="text-xs text-zinc-400 mt-2">
                {formatDate(episode.updated_at)} / {formatFileSize(episode.size)}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}