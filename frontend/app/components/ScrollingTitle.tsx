"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);

  const [isOverflowing, setIsOverflowing] = useState(false);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const check = () => {
      const container = containerRef.current;
      const textEl = textRef.current;

      if (!container || !textEl) return;

      const diff = textEl.scrollWidth - container.clientWidth;

      setIsOverflowing(diff > 4);
      setDistance(Math.max(diff, 0));
    };

    check();
    window.addEventListener("resize", check);

    return () => {
      window.removeEventListener("resize", check);
    };
  }, [text]);

  const duration = Math.min(Math.max(distance / 12, 6), 16);

  return (
    <div
      ref={containerRef}
      className={`relative w-full overflow-hidden whitespace-nowrap ${className}`}
      title={text}
    >
      <span
        ref={textRef}
        className={
          isOverflowing
            ? "inline-block whitespace-nowrap animate-title-scroll"
            : "block whitespace-nowrap overflow-hidden text-ellipsis"
        }
        style={
          isOverflowing
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
        .animate-title-scroll {
          animation: title-scroll var(--scroll-duration) linear infinite alternate;
          animation-delay: 1.2s;
        }

        @keyframes title-scroll {
          0% {
            transform: translateX(0);
          }

          20% {
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