"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

type Broadcast = {
  id: string;
  station: string;
  title: string;
  starts_at: string;
  ends_at: string;
};

export type Reservation = {
  id: string;
  program_id: string;
  title: string;
  mode: "once" | "weekly";
  state: string;
  message: string;
  updated_at: string;
  broadcast: Broadcast;
  jobs: { state: string; payload: Broadcast }[];
};

const labels: Record<string, string> = {
  pending_create: "登録処理中・未確認",
  create_failed: "登録失敗・未予約",
  create_unknown: "予約状態を確認できません",
  pending_cancel: "解除処理中",
  cancel_failed: "解除失敗・予約を確認してください",
  cancel_unknown: "解除結果不明・予約が残っている可能性があります",
  cancelled: "解除済み",
  completed: "放送時間終了",
  stale: "予約状態の確認が遅れています",
};

const buttonClass = "min-h-11 rounded-xl border border-zinc-600 px-4 py-3 text-sm font-bold disabled:opacity-50";

function dateLabel(value: string) {
  return new Date(value).toLocaleString("ja-JP", {
    timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit",
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init?.signal?.aborted) abort();
  init?.signal?.addEventListener("abort", abort, { once: true });
  const timeout = window.setTimeout(abort, 60000);
  let response: Response;
  try {
    response = await fetch(path, { ...init, signal: controller.signal, cache: "no-store" });
  } catch {
    throw new Error("応答を確認できません。接続を確認してください。予約操作の後は一覧から状態を再確認してください。");
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", abort);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof data?.detail?.message === "string" ? data.detail.message : "予約情報を取得・更新できませんでした。接続を確認して再度お試しください。");
  }
  return data as T;
}

export function useReservations() {
  const [items, setItems] = useState<Reservation[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const current = ++generation.current;
    try {
      const data = await request<Reservation[]>("/api/reservations", { signal });
      if (current !== generation.current || signal?.aborted) return;
      if (!Array.isArray(data)) throw new Error("予約一覧の形式を確認できません。再度お試しください。");
      setItems(data);
      setError("");
    } catch (error) {
      if (current === generation.current && !signal?.aborted) setError(error instanceof Error ? error.message : "予約一覧を取得できません。");
    } finally {
      if (current === generation.current && !signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void reload(controller.signal), 0);
    const timer = window.setInterval(() => { if (!inFlight.current) void reload(controller.signal); }, 30000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); controller.abort(); };
  }, [reload]);

  async function mutate(path: string, init: RequestInit) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setNotice("");
    try {
      const result = await request<Reservation | Reservation[]>(path, init);
      if (!Array.isArray(result)) {
        setNotice(result.message || (result.state === "active" ? "予約を登録しました。" : result.state === "cancelled" ? "予約を解除しました。" : "予約状態を更新しました。"));
      } else {
        setNotice("録音側の状態を確認しました。各予約の状態をご確認ください。");
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作結果を確認できません。状態を再確認してください。");
    } finally {
      await reload();
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { items, error, notice, loading, busy, reload, mutate };
}

type Manager = ReturnType<typeof useReservations>;

export function ReservationBadge({ items, programId, unavailable = false }: {
  items: Reservation[]; programId: string; unavailable?: boolean;
}) {
  const related = items.filter((item) => item.program_id === programId && !["cancelled", "completed"].includes(item.state));
  if (unavailable) return <span className="mt-1 block text-xs text-amber-300">予約状態を取得できません</span>;
  if (!related.length) return null;
  return <span className="mt-1 block text-xs text-amber-300">{related.map((item) =>
    item.state === "active" ? item.mode === "weekly" ? "毎週予約" : "今回予約済み" : labels[item.state] || "要確認"
  ).filter((value, index, list) => list.indexOf(value) === index).join(" / ")}</span>;
}

export function ReservationMessages({ manager }: { manager: Manager }) {
  return <div aria-live="polite" className="space-y-2 text-sm">
    {manager.error && <p role="alert" className="rounded-xl bg-red-950 p-3 text-red-200">{manager.error}</p>}
    {manager.notice && <p className="rounded-xl bg-zinc-800 p-3">{manager.notice}</p>}
  </div>;
}

function ReservationRow({ item, manager }: { item: Reservation; manager: Manager }) {
  const terminal = ["cancelled", "completed"].includes(item.state);
  const latest = item.jobs?.[item.jobs.length - 1]?.payload || item.broadcast;
  return <article className="space-y-3 rounded-2xl border border-zinc-700 p-4">
    <p className="break-words font-bold">{item.title}</p>
    <p className="text-sm text-zinc-300">{item.mode === "weekly" ? "毎週・同じ曜日と時間帯" : "今回のみ"} / {latest.station}<br />
      {dateLabel(latest.starts_at)} 〜 {dateLabel(latest.ends_at)}（日本時間）</p>
    <p className="text-sm font-bold text-amber-300">{item.state === "active" ? "予約済み" : labels[item.state] || "要確認"}</p>
    {item.message && <p className="text-sm text-amber-200">{item.message}</p>}
    <p className="text-xs text-zinc-400">最終確認: {dateLabel(item.updated_at)}</p>
    {!terminal && <div className="flex flex-wrap gap-2">
      <button type="button" disabled={manager.busy} className={buttonClass}
        onClick={() => {
          if (window.confirm(item.mode === "weekly" ? "毎週予約と未開始の予約を解除しますか？" : "この予約を解除しますか？")) {
            void manager.mutate(`/api/reservations/${item.id}`, { method: "DELETE" });
          }
        }}>予約を解除</button>
      <button type="button" disabled={manager.busy} className={buttonClass}
        onClick={() => void manager.mutate(`/api/reservations/${item.id}/refresh`, { method: "POST" })}>状態を再確認</button>
      {item.state === "create_failed" && <button type="button" disabled={manager.busy} className={buttonClass}
        onClick={() => void manager.mutate(`/api/reservations/${item.id}/retry`, { method: "POST" })}>再登録</button>}
    </div>}
  </article>;
}

export function ReservationList({ manager, programId }: { manager: Manager; programId?: string }) {
  const items = manager.items.filter((item) => !programId || (item.program_id === programId && !["cancelled", "completed"].includes(item.state)));
  return <div className="space-y-3" aria-busy={manager.busy || manager.loading}>
    {manager.loading && <p className="text-sm text-zinc-400">予約一覧を読み込み中…</p>}
    {!manager.loading && !manager.error && !items.length && <p className="text-sm text-zinc-400">予約はありません。</p>}
    {items.map((item) => <ReservationRow key={item.id} item={item} manager={manager} />)}
  </div>;
}

export function ReservationPanel({ programId, manager }: { programId: string; manager: Manager }) {
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    request<{ broadcasts: Broadcast[]; message: string }>(`/api/programs/${programId}/broadcasts`, { signal: controller.signal })
      .then((data) => {
        if (!Array.isArray(data?.broadcasts)) throw new Error("放送予定を確認できません。再度お試しください。");
        if (!controller.signal.aborted) { setBroadcasts(data.broadcasts); setMessage(data.message); }
      })
      .catch((error) => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "放送予定を取得できません。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [programId, attempt]);
  const chosen = broadcasts.find((item) => item.id === selected) || broadcasts[0];
  const alreadyReserved = manager.items.some((item) => item.program_id === programId &&
    !["completed", "cancelled"].includes(item.state) && (item.mode === "weekly" || item.broadcast.id === chosen?.id));
  const disabled = manager.busy || manager.loading || !!manager.error || loading || !chosen || alreadyReserved;
  const visibleMessage = loading ? "" : message;
  function reserve(mode: "once" | "weekly") {
    if (!chosen || disabled) return;
    void manager.mutate("/api/reservations", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program_id: programId, broadcast_id: chosen.id, mode }) });
  }
  return <section className="mt-5 space-y-4 rounded-3xl bg-zinc-900 p-4" aria-label="録音予約">
    <div className="flex items-center justify-between gap-2"><h2 className="text-lg font-bold">録音予約</h2>
      <Link href="/reservations" className="inline-flex min-h-11 items-center text-sm underline">予約一覧</Link></div>
    <ReservationMessages manager={manager} />
    {loading && <p role="status" className="text-sm text-zinc-400">次回の放送予定を確認中…</p>}
    {visibleMessage && <p role="status" className="text-sm text-amber-200">{visibleMessage}</p>}
    {!loading && <button type="button" className={buttonClass} disabled={manager.busy} onClick={() => {
      setLoading(true); setBroadcasts([]); setMessage(""); setAttempt((value) => value + 1);
    }}>放送予定を再取得</button>}
    {chosen && !loading && <>
      <label className="block text-sm">予約する放送回（日本時間）
        <select value={chosen.id} onChange={(event) => setSelected(event.target.value)} disabled={manager.busy}
          className="mt-2 min-h-11 w-full min-w-0 rounded-xl border border-zinc-600 bg-zinc-950 p-2 text-base">
          {broadcasts.map((item) => <option key={item.id} value={item.id}>{dateLabel(item.starts_at)} / {item.station}</option>)}
        </select>
      </label>
      <p className="break-words text-sm">{chosen.title}<br />{dateLabel(chosen.starts_at)} 〜 {dateLabel(chosen.ends_at)}</p>
    </>}
    <div className="grid grid-cols-2 gap-2">
      <button type="button" className={`${buttonClass} bg-white text-zinc-950`} disabled={disabled} onClick={() => reserve("once")}>今回だけ録音</button>
      <button type="button" className={`${buttonClass} bg-white text-zinc-950`} disabled={disabled} onClick={() => reserve("weekly")}>毎週録音</button>
    </div>
    <p className="text-xs leading-5 text-zinc-400">毎週録音は同じ放送局・曜日・時間帯の固定枠です。特番や時間変更には追従しません。実際の録音はrfriends3が行います。</p>
    {manager.busy && <p role="status" className="text-sm">録音側に反映中…</p>}
    <ReservationList manager={manager} programId={programId} />
  </section>;
}
