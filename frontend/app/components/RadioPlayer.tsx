"use client";

import { useEffect, useMemo, useRef, useState } from "react";

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

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds)) {
    return "0:00";
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
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
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [statusMessage, setStatusMessage] = useState("待機中");

  const currentEpisode = episodes[currentIndex];

  const audioUrl = useMemo(() => {
    if (!currentEpisode) {
      return "";
    }

    return createAudioUrl(publicApiBaseUrl, programId, currentEpisode.filename);
  }, [currentEpisode, programId, publicApiBaseUrl]);

  useEffect(() => {
    const audio = audioRef.current;

    if (!audio) {
      return;
    }

    function handleTimeUpdate() {
      setCurrentTime(audio.currentTime || 0);
    }

    function handleLoadedMetadata() {
      setDuration(audio.duration || 0);
      setStatusMessage("音声データを読み込みました");
    }

    function handleCanPlay() {
      setStatusMessage("再生できます");
    }

    function handlePlay() {
      setIsPlaying(true);
      setStatusMessage("再生中");
    }

    function handlePause() {
      setIsPlaying(false);
      setStatusMessage("一時停止中");
    }

    function handleEnded() {
      setIsPlaying(false);
      setStatusMessage("再生終了");

      if (currentIndex < episodes.length - 1) {
        moveEpisode(currentIndex + 1, true);
      }
    }

    function handleError() {
      const errorCode = audio.error?.code ?? "unknown";
      setIsPlaying(false);
      setStatusMessage(`音声の読み込みに失敗しました code=${errorCode}`);
    }

    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("canplay", handleCanPlay);
    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("error", handleError);

    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("canplay", handleCanPlay);
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
    };
  }, [currentIndex, episodes.length]);

  function play() {
    const audio = audioRef.current;

    if (!audio) {
      setStatusMessage("audio要素が見つかりません");
      return;
    }

    setStatusMessage("再生を開始しています...");

    audio.play().catch((error) => {
      setIsPlaying(false);
      setStatusMessage(`再生に失敗しました: ${error.name}`);
    });
  }

  function pause() {
    const audio = audioRef.current;

    if (!audio) {
      return;
    }

    audio.pause();
  }

  function togglePlay() {
    if (isPlaying) {
      pause();
      return;
    }

    play();
  }

  function skip(seconds: number) {
    const audio = audioRef.current;

    if (!audio) {
      setStatusMessage("audio要素が見つかりません");
      return;
    }

    const nextTime = Math.max(
      0,
      Math.min(audio.duration || Infinity, audio.currentTime + seconds)
    );

    audio.currentTime = nextTime;
    setCurrentTime(nextTime);
    setStatusMessage(`${seconds > 0 ? seconds + "秒進めました" : Math.abs(seconds) + "秒戻しました"}`);
  }

  function moveEpisode(nextIndex: number, shouldPlay = isPlaying) {
    if (nextIndex < 0 || nextIndex >= episodes.length) {
      return;
    }

    setCurrentIndex(nextIndex);
    setCurrentTime(0);
    setDuration(0);
    setIsPlaying(false);
    setStatusMessage("録音を切り替えました");

    setTimeout(() => {
      const audio = audioRef.current;

      if (!audio) {
        return;
      }

      audio.load();

      if (shouldPlay) {
        audio.play().catch((error) => {
          setIsPlaying(false);
          setStatusMessage(`切り替え後の再生に失敗しました: ${error.name}`);
        });
      }
    }, 0);
  }

  function seek(value: string) {
    const audio = audioRef.current;
    const nextTime = Number(value);

    if (!audio || Number.isNaN(nextTime)) {
      return;
    }

    audio.currentTime = nextTime;
    setCurrentTime(nextTime);
  }

  if (episodes.length === 0 || !currentEpisode) {
    return (
      <div className="bg-[#232428] border border-[#34363b] rounded-2xl p-4 text-zinc-400">
        録音データが見つかりません
      </div>
    );
  }

  const controlButton =
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

        <audio ref={audioRef} preload="metadata" src={audioUrl} />

        <div className="mt-5 rounded-3xl bg-zinc-950 border border-zinc-700 p-4">
          <button
            type="button"
            onClick={togglePlay}
            className="w-full rounded-2xl bg-white text-black py-4 text-xl font-black active:scale-95"
          >
            {isPlaying ? "⏸ 一時停止" : "▶ 再生"}
          </button>

          <div className="mt-3 text-sm text-yellow-300">
            {statusMessage}
          </div>

          <a
            href={audioUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2 block text-xs text-blue-300 underline break-all"
          >
            音声ファイルを直接開く
          </a>

          <div className="mt-4">
            <input
              type="range"
              min="0"
              max={duration || 0}
              value={currentTime}
              onChange={(event) => seek(event.target.value)}
              className="w-full"
            />

            <div className="flex justify-between text-xs text-zinc-400 mt-1">
              <span>{formatTime(currentTime)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mt-5">
            <button
              type="button"
              onClick={() => moveEpisode(currentIndex - 1)}
              disabled={currentIndex === 0}
              className={controlButton}
            >
              ⏮ 前の録音
            </button>

            <button
              type="button"
              onClick={() => skip(-15)}
              className={controlButton}
            >
              ↩ 15秒戻る
            </button>

            <button
              type="button"
              onClick={() => skip(30)}
              className={controlButton}
            >
              30秒進む ↪
            </button>

            <button
              type="button"
              onClick={() => moveEpisode(currentIndex + 1)}
              disabled={currentIndex === episodes.length - 1}
              className={controlButton}
            >
              次の録音 ⏭
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {episodes.map((episode, index) => {
          const isActive = index === currentIndex;

          return (
            <button
              key={episode.filename}
              type="button"
              onClick={() => moveEpisode(index, true)}
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