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
  created_at: string;
  updated_at: string;
  broadcast: Broadcast;
  jobs: { state: string; payload: Broadcast }[];
  subscription_id?: string | null;
};

export type WeeklySubscription = {
  id: string;
  program_id: string;
  station: string;
  title: string;
  state: "active" | "cancelled";
  schedule_state: string;
  cancel_requested?: number;
  current_reservation_id: string | null;
  last_matched_broadcast: Broadcast | null;
  next_expected_at: string;
  message: string;
  created_at: string;
  updated_at: string;
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
  waiting_write: "録音側への反映待ち",
};

const subscriptionLabels: Record<string, string> = {
  cancelling: "解除待ち・次回生成停止中",
  cancel_failed: "解除失敗・再試行してください",
  cancel_unknown: "解除結果不明・予約が残っている可能性があります",
  pending_cancel: "解除待ち・次回生成停止中",
  pending_create: "登録処理中",
  scheduled: "毎週録音中",
  waiting_write: "録音側への反映待ち",
  waiting_schedule: "次回放送待ち",
  schedule_unavailable: "番組表の再取得待ち",
  waiting_program: "番組情報の確認待ち",
  ambiguous: "次回候補を確認できません",
  create_failed: "次回予約の登録失敗",
  create_unknown: "次回予約の状態不明",
  cancelled: "解除済み",
};

const buttonClass = "min-h-11 rounded-xl border border-zinc-600 px-4 py-3 text-sm font-bold disabled:opacity-50";

function dateLabel(value: string) {
  return new Date(value).toLocaleString("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit",
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
  if (data === null || typeof data !== "object") {
    throw new Error("サーバーの応答を確認できません。予約一覧を再取得して状態を確認してください。");
  }
  return data as T;
}

export function useReservations() {
  const [{ items, subscriptions }, setSnapshot] = useState<{
    items: Reservation[]; subscriptions: WeeklySubscription[];
  }>({ items: [], subscriptions: [] });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const current = ++generation.current;
    try {
      const [data, weekly] = await Promise.all([
        request<Reservation[]>("/api/reservations", { signal }),
        request<WeeklySubscription[]>("/api/subscriptions", { signal }),
      ]);
      if (current !== generation.current || signal?.aborted) return false;
      if (!Array.isArray(data)) throw new Error("予約一覧の形式を確認できません。再度お試しください。");
      if (!Array.isArray(weekly)) throw new Error("毎週録音一覧の形式を確認できません。再度お試しください。");
      setSnapshot({ items: data, subscriptions: weekly });
      setError("");
      return true;
    } catch (error) {
      if (current === generation.current && !signal?.aborted) setError(error instanceof Error ? error.message : "予約一覧を取得できません。");
      return false;
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
    // Ignore list requests started before this mutation, including polling.
    ++generation.current;
    setBusy(true);
    setNotice("");
    let resultNotice = "";
    try {
      const result = await request<Reservation | WeeklySubscription | Reservation[]>(path, init);
      if (init.method === "DELETE" && path.startsWith("/api/subscriptions/")) {
        const expectedId = path.slice("/api/subscriptions/".length);
        if (!("schedule_state" in result) || result.id !== expectedId) {
          throw new Error("解除対象を確認できません。予約一覧を再取得して状態を確認してください。");
        }
        if (result.state !== "cancelled" || result.schedule_state !== "cancelled") {
          throw new Error(result.message || "毎週録音の解除を確認できませんでした。予約一覧から状態を確認してください。");
        }
      }
      if (!Array.isArray(result)) {
        resultNotice = ("cancel_requested" in result && result.cancel_requested && result.state === "active" ? result.message || "解除は完了していません。状態を確認して再試行してください。" : result.message) ||
          (result.state === "cancelled" ? "予約を解除しました。" : "schedule_state" in result
            ? result.schedule_state === "scheduled" ? "毎週録音を登録しました。" : subscriptionLabels[result.schedule_state] || "毎週録音の状態を確認してください。"
            : result.state === "active" ? "予約を登録しました。" : "予約状態を更新しました。");
      } else {
        resultNotice = "録音側の状態を確認しました。各予約の状態をご確認ください。";
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作結果を確認できません。状態を再確認してください。");
    } finally {
      const refreshed = await reload();
      if (resultNotice) setNotice(refreshed ? resultNotice : "操作後の最新状態を取得できません。予約一覧を再取得して確認してください。");
      inFlight.current = false;
      setBusy(false);
    }
  }

  return { items, subscriptions, error, notice, loading, busy, reload, mutate };
}

type Manager = ReturnType<typeof useReservations>;

export function ReservationBadge({ items, subscriptions, programId, unavailable = false }: {
  items: Reservation[]; subscriptions: WeeklySubscription[]; programId: string; unavailable?: boolean;
}) {
  const related = items.filter((item) => !item.subscription_id && item.program_id === programId && !["cancelled", "completed"].includes(item.state));
  const weekly = subscriptions.find((item) => item.program_id === programId && item.state === "active");
  if (unavailable) return <span className="mt-1 block text-xs text-amber-300">予約状態を取得できません</span>;
  const values = related.map((item) => item.state === "active" ? "今回予約済み" : labels[item.state] || "要確認");
  if (weekly) values.unshift(weekly.cancel_requested ? "毎週録音の解除未完了" : subscriptionLabels[weekly.schedule_state] || "毎週録音・要確認");
  if (!values.length) return null;
  return <span className="mt-1 block text-xs text-amber-300">{values.filter((value, index, list) => list.indexOf(value) === index).join(" / ")}</span>;
}

export function ReservationMessages({ manager }: { manager: Manager }) {
  return <div aria-live="polite" className="space-y-2 text-sm">
    {manager.error && <p role="alert" className="rounded-xl bg-red-950 p-3 text-red-200">{manager.error}</p>}
    {manager.notice && <p className="rounded-xl bg-zinc-800 p-3">{manager.notice}</p>}
  </div>;
}

function ReservationRow({ item, manager, historyOnly = false }: { item: Reservation; manager: Manager; historyOnly?: boolean }) {
  const terminal = ["cancelled", "completed"].includes(item.state);
  const latest = item.jobs?.[item.jobs.length - 1]?.payload || item.broadcast;
  return <article className="space-y-3 rounded-2xl border border-zinc-700 p-4">
    <p className="break-words font-bold">{item.title}</p>
    <p className="text-sm text-zinc-300">{item.subscription_id ? "毎週録音の放送回" : "今回のみ"} / {latest.station}<br />
      {dateLabel(latest.starts_at)} 〜 {dateLabel(latest.ends_at)}（日本時間）</p>
    <p className="text-sm font-bold text-amber-300">{item.state === "active" ? "予約済み" : labels[item.state] || "要確認"}</p>
    {item.message && <p className="text-sm text-amber-200">{item.message}</p>}
    <p className="break-all text-xs text-zinc-400">RadioFlix予約ID: {item.id}</p>
    <p className="text-xs text-zinc-400">作成: {dateLabel(item.created_at)}<br />更新: {dateLabel(item.updated_at)}</p>
    {!terminal && !historyOnly && <div className="flex flex-wrap gap-2">
      <button type="button" disabled={manager.busy} className={buttonClass}
        onClick={() => {
          if (window.confirm("この予約を解除しますか？")) {
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

function SubscriptionRow({ item, manager }: { item: WeeklySubscription; manager: Manager }) {
  const occurrences = manager.items.filter((row) => row.subscription_id === item.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const current = occurrences.find((row) => row.id === item.current_reservation_id);
  const latest = current || occurrences[0];
  const next = item.state === "active" && current && !["completed", "cancelled"].includes(current.state) ? current.broadcast : null;
  const cancellationProblem = !!item.cancel_requested && item.state === "active";
  return <article className="space-y-3 rounded-2xl border border-amber-700/70 bg-amber-950/20 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="break-words font-bold">{item.title}</p>
      <span className="rounded-full bg-amber-300 px-2 py-1 text-xs font-bold text-zinc-950">{item.state === "cancelled" ? "毎週録音解除済み" : cancellationProblem ? "毎週録音の解除未完了" : item.schedule_state === "scheduled" ? "毎週録音中" : "毎週録音・待機／要確認"}</span>
    </div>
    <p className="text-sm text-zinc-300">{item.station}</p>
    <p className="text-sm">{next ? <>対象放送: {dateLabel(next.starts_at)} 〜 {dateLabel(next.ends_at)}</> : item.state === "cancelled" ? "毎週録音を解除しました" : "次回放送待ち"}</p>
    <p className="text-sm font-bold text-amber-300">{subscriptionLabels[item.schedule_state] || "状態確認中"}</p>
    {latest && <p className="text-sm">直近の放送回状態: {latest.state === "active" ? "予約登録成功" : labels[latest.state] || "要確認"}</p>}
    {item.message && <p role={cancellationProblem ? "alert" : undefined} className="break-words text-sm text-amber-200">{item.message}</p>}
    {cancellationProblem && <p className="text-sm text-amber-200">解除は完了していません。次回予約の生成を停止して再確認します。</p>}
    <p className="text-xs text-zinc-400">最終更新: {dateLabel(item.updated_at)}</p>
    {item.state === "active" && <button type="button" disabled={manager.busy} className={buttonClass}
      onClick={() => {
        if (window.confirm("毎週録音を停止し、RadioFlixが所有する未開始の次回予約を解除しますか？")) {
          void manager.mutate(`/api/subscriptions/${item.id}`, { method: "DELETE" });
        }
      }}>{cancellationProblem ? "毎週録音の解除を再試行" : "毎週録音を解除"}</button>}
    {item.state === "active" && current && <button type="button" disabled={manager.busy} className={buttonClass}
      onClick={() => void manager.mutate(`/api/reservations/${current.id}/refresh`, { method: "POST" })}>状態を再確認</button>}
  </article>;
}

export function ReservationList({ manager, programId }: { manager: Manager; programId?: string }) {
  const standalone = manager.items.filter((item) => !item.subscription_id && (!programId || item.program_id === programId));
  const active = standalone.filter((item) => !["cancelled", "completed"].includes(item.state));
  const history = manager.items.filter((item) => (!programId || item.program_id === programId) &&
    (item.subscription_id || ["cancelled", "completed"].includes(item.state)));
  const weekly = manager.subscriptions.filter((item) => item.state === "active" && (!programId || item.program_id === programId));
  const weeklyHistory = manager.subscriptions.filter((item) => item.state === "cancelled" && (!programId || item.program_id === programId));
  return <div className="space-y-3" aria-busy={manager.busy || manager.loading}>
    {manager.loading && <p className="text-sm text-zinc-400">予約一覧を読み込み中…</p>}
    {!manager.loading && !manager.error && !active.length && !weekly.length && !history.length && !weeklyHistory.length && <p className="text-sm text-zinc-400">予約はありません。</p>}
    {!!weekly.length && <section className="space-y-3"><h2 className="text-base font-bold">有効な毎週録音</h2>
      {weekly.map((item) => <SubscriptionRow key={item.id} item={item} manager={manager} />)}</section>}
    {!!active.length && <section className="space-y-3"><h2 className="text-base font-bold">有効な単発予約</h2>
      {active.map((item) => <ReservationRow key={item.id} item={item} manager={manager} />)}</section>}
    {(!!history.length || !!weeklyHistory.length) && <details className="rounded-2xl border border-zinc-800 p-3">
      <summary className="min-h-11 cursor-pointer py-2 font-bold">履歴・毎週の放送回（{history.length + weeklyHistory.length}）</summary>
      <div className="mt-3 space-y-3">{weeklyHistory.map((item) => <SubscriptionRow key={item.id} item={item} manager={manager} />)}
        {history.map((item) => <ReservationRow key={item.id} item={item} manager={manager} historyOnly />)}</div>
    </details>}
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
  const onceReserved = manager.items.some((item) => item.program_id === programId &&
    !["completed", "cancelled"].includes(item.state) && item.broadcast.id === chosen?.id);
  const weeklyActive = manager.subscriptions.some((item) => item.program_id === programId && item.state === "active");
  const baseDisabled = manager.busy || manager.loading || !!manager.error || loading || !chosen;
  const visibleMessage = loading ? "" : message;
  function reserve(mode: "once" | "weekly") {
    if (!chosen || baseDisabled || (mode === "once" ? onceReserved : weeklyActive)) return;
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
      <button type="button" className={`${buttonClass} bg-white text-zinc-950`} disabled={baseDisabled || onceReserved} onClick={() => reserve("once")}>今回だけ録音</button>
      <button type="button" className={`${buttonClass} bg-amber-300 text-zinc-950`} disabled={baseDisabled || weeklyActive} onClick={() => reserve("weekly")}>{weeklyActive ? "毎週録音中" : "毎週録音"}</button>
    </div>
    <p className="text-xs leading-5 text-zinc-400">毎週録音は次回の番組表を確認し、未来の1放送回だけを予約します。未公開や候補不明の場合は誤予約せず待機します。</p>
    {manager.busy && <p role="status" className="text-sm">録音側に反映中…</p>}
    <ReservationList manager={manager} programId={programId} />
  </section>;
}
