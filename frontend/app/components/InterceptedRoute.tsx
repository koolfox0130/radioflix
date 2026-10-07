"use client";

import { useContext } from "react";
import type { ReactNode } from "react";
import { PrimaryRouteContext } from "./PrimaryRouteContext";

export default function InterceptedRoute({ children, skipWhenSegment }: { children: ReactNode; skipWhenSegment: string }) {
  const activePage = useContext(PrimaryRouteContext);
  if (activePage === skipWhenSegment) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 top-12 z-50 overflow-y-auto overscroll-contain bg-zinc-950">
      {children}
    </div>
  );
}
