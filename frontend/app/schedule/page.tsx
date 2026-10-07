"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type Station = { id: string; name: string };
type Broadcast = {
  id: string; station: string; station_name: string; title: string; performer: string | null;
  starts_at: string; ends_at: string; schedule_revision: string;
  reservation_label: string; recording_state: string; native_state: string;
  allowed_actions: string[]; timefree_message: string;
};
type Schedule = { today: string; writes_enabled: boolean; days: { radio_date: string; availability: string; broadcasts: Broadcast[] }[] };
const failure = "この日の番組表を取得できませんでした";
function radioToday() { return new Date(Date.now() + 4 * 3600000).toISOString().slice(0, 10); }
function dateOffset(date: string, offset: number) { return new Date(Date.parse(date + "T12:00:00Z") + offset * 86400000).toISOString().slice(0, 10); }
function validDate(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value ? null : value;
}
function scheduleScrollKey(search = window.location.search) {
  return `radioflix-schedule-scroll:${search}`;
}
const savedScheduleKey = "radioflix-schedule-last-url";
function savedRailScroll(search = window.location.search) {
  const value = window.sessionStorage.getItem(scheduleScrollKey(search));
  return value === null || !Number.isFinite(Number(value)) ? null : Number(value);
}
function scheduleUrl(date: string, station: string) {
  const params = new URLSearchParams({ date });
  if (station) params.set("station", station);
  return `/schedule?${params.toString()}`;
}
function timeLabel(value: string, date: string) {
  const jst = new Date(Date.parse(value) + 9 * 3600000).toISOString();
  return (jst.slice(0, 10) > date ? "翌" : "") + jst.slice(11, 16);
}
async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail?.message || failure);
  return data;
}
function ScheduleContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [today, setToday] = useState(radioToday);
  const date = validDate(searchParams.get("date")) || today;
  const station = searchParams.get("station") || "";
  const [hydrated, setHydrated] = useState(false);
  const [stations, setStations] = useState<Station[]>([]);
  const [stationError, setStationError] = useState("");
  const [data, setData] = useState<Schedule | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submitting = useRef(false);
  const generation = useRef(0);
  const dateRail = useRef<HTMLDivElement>(null);
  const stationRail = useRef<HTMLDivElement>(null);
  const initialDate = useRef(date);
  const dateButtons = useRef(new Map<string, HTMLButtonElement>());
  const stationButtons = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    window.sessionStorage.setItem(savedScheduleKey, `${window.location.pathname}${window.location.search}`);
    const currentScroll = savedRailScroll();
    requestAnimationFrame(() => {
      setHydrated(true);
      requestAnimationFrame(() => {
      if (!dateRail.current) return;
      if (currentScroll !== null) dateRail.current.scrollLeft = currentScroll;
      else {
        const selected = dateButtons.current.get(initialDate.current);
        if (selected) dateRail.current.scrollLeft = selected.offsetLeft - (dateRail.current.clientWidth - selected.clientWidth) / 2;
        window.sessionStorage.setItem(scheduleScrollKey(), String(dateRail.current.scrollLeft));
      }
      });
    });
    const onPopState = () => {
      const next = new URLSearchParams(window.location.search);
      const nextDate = validDate(next.get("date")) || radioToday();
      const nextScroll = savedRailScroll();
      generation.current++;
      setLoading(true); setData(null); setError(""); setMessage("");
      setRefresh(value => value + 1);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (dateRail.current && nextScroll !== null) {
          dateRail.current.scrollLeft = nextScroll;
        } else if (dateRail.current) {
          const selected = dateButtons.current.get(nextDate);
          if (selected) dateRail.current.scrollLeft = selected.offsetLeft - (dateRail.current.clientWidth - selected.clientWidth) / 2;
          if (dateRail.current) window.sessionStorage.setItem(scheduleScrollKey(), String(dateRail.current.scrollLeft));
        }
      }));
    };
    const saveScroll = () => {
      if (dateRail.current) window.sessionStorage.setItem(scheduleScrollKey(), String(dateRail.current.scrollLeft));
    };
    window.addEventListener("popstate", onPopState);
    window.addEventListener("pagehide", saveScroll);
    return () => {
      saveScroll();
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("pagehide", saveScroll);
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api<{ stations: Station[] }>("/api/stations", { signal: controller.signal }).then(result => {
      setStations(result.stations); setStationError("");
    }).catch(() => { if (!controller.signal.aborted) setStationError("放送局一覧を取得できませんでした"); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (!hydrated) return;
    const controller = new AbortController();
    const current = ++generation.current;
    api<Schedule>(`/api/schedule?date=${date}${station ? `&station=${encodeURIComponent(station)}` : ""}`, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted || current !== generation.current) return;
      setData(result); setToday(result.today); setError(""); setLoading(false);
    }).catch(() => { if (!controller.signal.aborted && current === generation.current) { setError(failure); setLoading(false); } });
    return () => controller.abort();
  }, [station, date, refresh, hydrated]);
  function change(nextDate: string, nextStation: string) {
    if (nextDate === date && nextStation === station) return;
    if (dateRail.current) window.sessionStorage.setItem(scheduleScrollKey(), String(dateRail.current.scrollLeft));
    const stationChanged = nextDate === date;
    const nextUrl = scheduleUrl(nextDate, nextStation);
    window.sessionStorage.setItem(savedScheduleKey, nextUrl);
    const nextSearch = new URL(nextUrl, window.location.origin).search;
    if (stationChanged && dateRail.current) {
      window.sessionStorage.setItem(scheduleScrollKey(nextSearch), String(dateRail.current.scrollLeft));
    }
    router.push(nextUrl, { scroll: false });
    generation.current++; setLoading(true); setData(null); setError(""); setMessage("");
    requestAnimationFrame(() => {
      const rail = stationChanged ? stationRail.current : dateRail.current;
      const selected = stationChanged ? stationButtons.current.get(nextStation) : dateButtons.current.get(nextDate);
      if (rail && selected) {
        rail.scrollLeft = selected.offsetLeft - (rail.clientWidth - selected.clientWidth) / 2;
        if (!stationChanged) window.sessionStorage.setItem(scheduleScrollKey(nextSearch), String(dateRail.current?.scrollLeft || 0));
      }
    });
  }
  function reload() { generation.current++; setLoading(true); setData(null); setError(""); setRefresh(value => value + 1); }
  async function reserve(b: Broadcast, mode: string) {
    if (submitting.current) return;
    if (!navigator.onLine) { setMessage("オフラインでは予約できません。"); return; }
    submitting.current = true; setBusy(true); setMessage("予約状態を確認中…");
    try {
      const result = await api<{state: string; schedule_state?: string; message?: string}>(`/api/broadcasts/${b.id}/reservations`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, schedule_revision: b.schedule_revision, mode }),
      });
      const state = result.schedule_state || result.state;
      setMessage(state === "waiting_write" ? "書き込み無効のため待機中です。実予約は行われていません。" :
        ["scheduled", "active"].includes(state) ? (mode === "weekly" ? "毎週録音中" : "今回のみ予約済み") : result.message || "予約状態を確認してください。");
    } catch (e) { setMessage(e instanceof Error ? e.message : "予約結果を確認できません。予約一覧を確認してください。"); }
    finally { submitting.current = false; setBusy(false); reload(); }
  }
  const day = data?.days.find(d => d.radio_date === date);
  return <main className="min-h-screen bg-zinc-950 text-base text-zinc-100">
    <div className="mx-auto max-w-2xl space-y-4 px-3 py-5">
      <h1 className="text-2xl font-bold">番組表</h1>
      <p className="text-sm text-zinc-400">日本時間・放送日は05:00に切り替わります。</p>
      <div>
        <h2 className="mb-2 text-sm font-medium">放送局</h2>
        <div ref={stationRail} aria-label="放送局" className="flex max-w-full gap-2 overflow-x-auto pb-2">
          {[["", "すべての局"], ...stations.map(s => [s.id, s.name])].map(([id, name]) =>
            <button type="button" key={id}
              ref={node => { if (node) stationButtons.current.set(id, node); else stationButtons.current.delete(id); }}
              aria-pressed={station === id} disabled={busy} onClick={() => change(date, id)}
              className={`min-h-12 shrink-0 rounded-full border px-4 ${station === id ? "border-white bg-zinc-700 font-bold" : "border-zinc-700"}`}>
              {name}
            </button>)}
        </div>
      </div>
      {stationError && <p role="alert">{stationError}</p>}
      <div ref={dateRail} aria-label="放送日" className="flex max-w-full gap-2 overflow-x-auto pb-2">
        {Array.from({ length: 15 }, (_, i) => dateOffset(today, i - 7)).map(d => <button type="button" key={d}
          ref={node => { if (node) dateButtons.current.set(d, node); else dateButtons.current.delete(d); }}
          aria-pressed={d === date} disabled={busy} onClick={() => change(d, station)}
          className={`min-h-12 shrink-0 rounded-lg border px-4 ${d === date ? "border-white bg-zinc-700" : "border-zinc-700"}`}>
          {d.slice(5).replace("-", "/")}({"日月火水木金土"[new Date(`${d}T00:00:00Z`).getUTCDay()]}){d === today ? " 今日" : ""}</button>)}
      </div>
      <h2 className="font-bold">{date} の番組</h2>
      <button type="button" disabled={busy || loading} onClick={reload} className="min-h-12 rounded-lg border px-4 disabled:opacity-50">再読み込み</button>
      {data && !data.writes_enabled && <p className="text-amber-200">録音連携は書き込み無効です。予約操作は待機として保存されます。</p>}
      {message && <p role="status" className="break-words text-amber-200">{message}</p>}
      {loading ? <p role="status">番組表を読み込み中…</p> : error || !day || day.availability !== "ok" ? <p role="alert">{failure}</p> :
        <div className="space-y-3">{day.broadcasts.map(b => <details key={b.id} className="rounded-xl border border-zinc-700 bg-zinc-900 p-4">
          <summary className="min-h-12 cursor-pointer break-words">
            <span className="block text-sm text-zinc-300">{timeLabel(b.starts_at, date)}〜{timeLabel(b.ends_at, date)} · {b.station_name}</span>
            <span className="my-2 block font-bold">{b.title}</span>
            {b.performer && <span className="block">{b.performer}</span>}
            <span className="mt-2 block text-sm text-amber-200">{b.reservation_label}</span>
          </summary>
          <div className="mt-4 space-y-3">
            <p className="text-sm text-zinc-400">録音状態：未確認</p>
            {b.native_state === "unknown" && <p className="text-sm text-zinc-400">rfriends3の既存予約は未確認です。</p>}
            {b.allowed_actions.length > 0 && <div className="flex flex-wrap gap-2">
              {[["once", "今回だけ録音"], ["weekly", "毎週録音"]].map(([mode, label]) => <button type="button" key={mode}
                disabled={busy || !b.allowed_actions.includes(mode)} onClick={() => void reserve(b, mode)}
                className="min-h-12 flex-1 rounded-lg bg-white px-3 py-2 text-zinc-950 disabled:opacity-40">{label}</button>)}
            </div>}
            {b.timefree_message && <p>{b.timefree_message}</p>}
            {!b.timefree_message && !b.allowed_actions.length && b.reservation_label === "未予約" && <p>開始直前のため予約できません。</p>}
          </div>
        </details>)}</div>}
    </div>
  </main>;
}

export default function SchedulePage() {
  return <Suspense fallback={<main className="min-h-screen bg-zinc-950 px-3 py-5 text-base text-zinc-100"><p role="status">番組表を読み込み中…</p></main>}>
    <ScheduleContent />
  </Suspense>;
}
