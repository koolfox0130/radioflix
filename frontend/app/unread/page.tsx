"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Program = {
  id: string;
  title: string;
  network?: string;
  category?: string;
  raw_name?: string;
  thumbnail_url?: string;
};

type Episode = {
  filename: string;
  title: string;
  size: number;
  updated_at: number;
  thumbnail_url?: string;
  audio_url?: string;
};

type UnreadEpisode = {
  program: Program;
  episode: Episode;
};

function getDisplayTitle(program: Program) {
  return program.title
    ?.replace(/^LFR_/, "")
    .replace(/^TBS_/, "")
    .replace(/^JUNK-/, "")
    .replace(/_/g, " ")
    .trim();
}

function getDisplayEpisodeTitle(episode: Episode) {
  return episode.title
    .replace(/_/g, " ")
    .replace(/\.m4a$/i, "")
    .replace(/\.mp3$/i, "")
    .replace(/\.aac$/i, "")
    .replace(/\.wav$/i, "")
    .trim();
}

function formatUpdatedAt(updatedAt: number) {
  if (!updatedAt) return "日付不明";

  const date = new Date(updatedAt * 1000);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}/${month}/${day}`;
}

function ProgramImage({
  apiBaseUrl,
  program,
}: {
  apiBaseUrl: string;
  program: Program;
}) {
  const imageUrl = program.thumbnail_url
    ? `${apiBaseUrl}${program.thumbnail_url}`
    : "";

  if (!imageUrl) {
    return (
      <div className="h-20 w-20 shrink-0 rounded-2xl bg-zinc-800 text-xs font-bold text-zinc-500 flex items-center justify-center">
        RadioFlix
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={program.title}
      className="h-20 w-20 shrink-0 rounded-2xl object-cover"
    />
  );
}

export default function UnreadPage() {
  const [unreadEpisodes, setUnreadEpisodes] = useState<UnreadEpisode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const apiBaseUrl = "";

  useEffect(() => {
    async function loadUnreadEpisodes() {
      try {
        const programsResponse = await fetch(`${apiBaseUrl}/programs`);

        if (!programsResponse.ok) {
          throw new Error("番組一覧を取得できませんでした");
        }

        const programsData = await programsResponse.json();
        const programs: Program[] = Array.isArray(programsData) ? programsData : [];

        const allEpisodeGroups = await Promise.all(
          programs.map(async (program) => {
            try {
              const response = await fetch(
                `${apiBaseUrl}/programs/${program.id}/episodes`
              );

              if (!response.ok) {
                return { program, episodes: [] as Episode[] };
              }

              const data = await response.json();
              return {
                program,
                episodes: Array.isArray(data) ? data : [],
              };
            } catch {
              return { program, episodes: [] as Episode[] };
            }
          })
        );

        const unreadCandidates: UnreadEpisode[] = [];

        for (const group of allEpisodeGroups) {
          for (const episode of group.episodes) {
            const key = `radioflix-position:${group.program.id}:${episode.filename}`;
            const rawValue = window.localStorage.getItem(key);

            if (!rawValue) {
              unreadCandidates.push({ program: group.program, episode });
              continue;
            }

            try {
              const parsed = JSON.parse(rawValue);
              const currentTime = Number(parsed.currentTime ?? 0);
              const duration = Number(parsed.duration ?? 0);

              if (currentTime < 5) {
                unreadCandidates.push({ program: group.program, episode });
              }
            } catch {
              unreadCandidates.push({ program: group.program, episode });
            }
          }
        }

        unreadCandidates.sort(
          (a, b) => b.episode.updated_at - a.episode.updated_at
        );

        setUnreadEpisodes(unreadCandidates);
      } catch (err) {
        console.error(err);
        setError("未聴エピソードを取得できませんでした");
      } finally {
        setLoading(false);
      }
    }

    loadUnreadEpisodes();
  }, [apiBaseUrl]);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-md px-4 pb-24 pt-5">
        <div className="mb-5 flex items-center gap-4 text-sm font-bold text-zinc-100">
          <Link href="/" className="rounded-2xl bg-zinc-900 px-3 py-2">
            ← 戻る
          </Link>
          <h1 className="text-lg">未聴</h1>
        </div>

        {loading && (
          <div className="rounded-3xl bg-zinc-900 p-5 text-sm text-zinc-400">
            未聴エピソードを読み込み中...
          </div>
        )}

        {error && (
          <div className="rounded-3xl border border-red-500/40 bg-red-950/40 p-5 text-sm text-red-200">
            {error}
          </div>
        )}

        {!loading && !error && unreadEpisodes.length === 0 && (
          <div className="rounded-3xl bg-zinc-900 p-5 text-sm text-zinc-400">
            未聴のエピソードはありません。
          </div>
        )}

        {!loading && !error && unreadEpisodes.length > 0 && (
          <div className="space-y-3">
            {unreadEpisodes.map((item) => (
              <Link
                key={`${item.program.id}:${item.episode.filename}`}
                href={`/?programId=${encodeURIComponent(
                  item.program.id
                )}&episodeFilename=${encodeURIComponent(
                  item.episode.filename
                )}&autoPlay=1`}
                className="block overflow-hidden rounded-3xl bg-zinc-900 p-3 transition active:scale-[0.99]"
              >
                <div className="flex items-center gap-3">
                  <ProgramImage apiBaseUrl={apiBaseUrl} program={item.program} />
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate font-bold">
                      {getDisplayTitle(item.program)}
                    </h2>
                    <p className="mt-1 text-xs text-zinc-500">
                      {formatUpdatedAt(item.episode.updated_at)}
                    </p>
                    <p className="mt-2 line-clamp-2 text-sm text-zinc-400">
                      {getDisplayEpisodeTitle(item.episode)}
                    </p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
