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
      setDistance(Math.max(diff + 24, 0));
    };

    check();

    const timer = setTimeout(check, 300);
    window.addEventListener("resize", check);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", check);
    };
  }, [text]);

  const duration = Math.min(Math.max(distance / 10, 8), 18);

  return (
    <div
      ref={containerRef}
      className={`relative w-full overflow-hidden whitespace-nowrap ${className}`}
      title={text}
    >
      <span
        ref={textRef}
        className={
          shouldScroll
            ? "inline-block whitespace-nowrap radioflix-marquee"
            : "block whitespace-nowrap overflow-hidden text-ellipsis"
        }
        style={
          shouldScroll
            ? ({
                "--scroll-distance": `${distance}px`,
                "--scroll-duration": `${duration}s`,
              } as React.CSSProperties)
            : undefined
        }
      >
        {text}
      </span>

      <style jsx>{`
        .radioflix-marquee {
          animation: radioflix-marquee var(--scroll-duration) ease-in-out
            infinite alternate;
          animation-delay: 1s;
        }

        @keyframes radioflix-marquee {
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