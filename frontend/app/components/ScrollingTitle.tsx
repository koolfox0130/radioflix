"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);

  const [shouldScroll, setShouldScroll] = useState(false);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const check = () => {
      const container = containerRef.current;
      const textEl = textRef.current;

      if (!container || !textEl) return;

      const diff = textEl.scrollWidth - container.clientWidth;

      setShouldScroll(diff > 8);
      setDistance(Math.max(diff + 32, 0));
    };

    check();

    const timer = setTimeout(check, 500);
    window.addEventListener("resize", check);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", check);
    };
  }, [text]);

  const duration = Math.min(Math.max(distance / 10, 8), 20);

  return (
    <div
      ref={containerRef}
      className={className}
      title={text}
      style={{
        width: "100%",
        overflow: "hidden",
        whiteSpace: "nowrap",
        wordBreak: "normal",
        overflowWrap: "normal",
        lineHeight: 1.4,
      }}
    >
      <span
        ref={textRef}
        style={{
          display: "inline-block",
          whiteSpace: "nowrap",
          wordBreak: "normal",
          overflowWrap: "normal",
          maxWidth: shouldScroll ? "none" : "100%",
          overflow: shouldScroll ? "visible" : "hidden",
          textOverflow: shouldScroll ? "clip" : "ellipsis",
          animation: shouldScroll
            ? `radioflix-title-scroll ${duration}s ease-in-out 1s infinite alternate`
            : "none",
          ["--scroll-distance" as string]: `${distance}px`,
        }}
      >
        {text}
      </span>

      <style jsx>{`
        @keyframes radioflix-title-scroll {
          0% {
            transform: translateX(0);
          }

          25% {
            transform: translateX(0);
          }

          100% {
            transform: translateX(calc(var(--scroll-distance) * -1));
          }
        }
      `}</style>
    </div>
  );
}