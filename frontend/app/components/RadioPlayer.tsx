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
        // ブラウザの自動再生制限で失敗することがあるので無視
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

  const buttonBase =
    "rounded-2xl border border-zinc-600 bg-zinc-800 px-4 py-4 text-base font-black text-white shadow active:scale-95 disabled:opacity-30 disabled:active:scale-100";

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

        <div className="grid grid-cols-2 gap-3 mt-5">
          <button
            type="button"
            onClick={playPreviousEpisode}
            disabled={currentIndex === 0}
            className={buttonBase}
          >
            ⏮ 前の録音
          </button>

          <button
            type="button"
            onClick={() => skip(-15)}
            className={buttonBase}
          >
            ↩ 15秒戻る
          </button>

          <button
            type="button"
            onClick={() => skip(30)}
            className={buttonBase}
          >
            30秒進む ↪
          </button>

          <button
            type="button"
            onClick={playNextEpisode}
            disabled={currentIndex === episodes.length - 1}
            className={buttonBase}
          >
            次の録音 ⏭
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
              className={`w-full text-left rounded-2xl border p-4 active:scale-[0.99] ${
                isActive
                  ? "bg-yellow-300/10 border-yellow-300/70"
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