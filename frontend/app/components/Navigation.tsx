"use client";
import { useEffect, type MouseEvent, type ReactNode } from "react";
import { usePathname, useRouter, useSelectedLayoutSegment } from "next/navigation";
import Link from "next/link";
import { PrimaryRouteContext } from "./PrimaryRouteContext";

const savedScheduleKey = "radioflix-schedule-last-url";

export default function Navigation({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const primaryRoute = useSelectedLayoutSegment() || "";

  useEffect(() => {
    if (path === "/schedule") {
      const current = `${window.location.pathname}${window.location.search}`;
      window.sessionStorage.setItem(savedScheduleKey, current);
    }
  }, [path]);

  function navigate(href: string, event: MouseEvent<HTMLAnchorElement>) {
    if (path === "/schedule") {
      window.sessionStorage.setItem(savedScheduleKey, `${window.location.pathname}${window.location.search}`);
    } else if (href === "/schedule") {
      const saved = window.sessionStorage.getItem(savedScheduleKey);
      if (saved?.startsWith("/schedule?")) {
        event.preventDefault();
        router.push(saved);
      }
    }
  }

  return <PrimaryRouteContext.Provider value={primaryRoute}>
    <nav aria-label="メインナビゲーション" className="flex w-full justify-center gap-1 bg-zinc-950 px-2 text-zinc-100">
    {[["/", "録音一覧"], ["/schedule", "番組表"], ["/reservations", "予約一覧"]].map(([href, label]) =>
      <Link key={href} href={href} onClick={event => navigate(href, event)}
        aria-current={path === href ? "page" : undefined}
        className={`flex min-h-12 items-center rounded-lg px-4 ${path === href ? "bg-zinc-700 font-bold" : "underline"}`}>{label}</Link>)}
    </nav>
    {children}
  </PrimaryRouteContext.Provider>;
}
