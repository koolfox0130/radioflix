"use client";

import Link from "next/link";
import { ReservationList, ReservationMessages, useReservations } from "../components/Reservations";

export default function ReservationsPage() {
  const manager = useReservations();
  return <main className="min-h-screen bg-zinc-950 text-zinc-100">
    <div className="mx-auto max-w-md space-y-5 px-4 py-6">
      <Link href="/" className="inline-flex min-h-11 items-center underline">← ホーム</Link>
      <h1 className="text-2xl font-bold">録音予約一覧</h1>
      <p className="text-sm text-zinc-400">RadioFlixから登録した予約です。rfriends3で直接登録した予約は、この一覧には含まれません。</p>
      <button type="button" disabled={manager.busy} onClick={() => void manager.reload()}
        className="min-h-11 rounded-xl border border-zinc-600 px-4 py-2 disabled:opacity-50">一覧を更新</button>
      <ReservationMessages manager={manager} />
      <ReservationList manager={manager} />
      <p className="text-xs text-zinc-400">「放送時間終了」は録音成功を保証しません。録音一覧でファイルを確認してください。</p>
    </div>
  </main>;
}
