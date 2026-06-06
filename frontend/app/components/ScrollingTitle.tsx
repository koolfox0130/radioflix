"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const measureRef = useRef<HTMLSpanElement | null>(null);

  const [isOverflowing, setIsOverflowing] = useState(false);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const checkOverflow = () => {
      const container = containerRef.current;
      const measure = measureRef.current;

      if (!container || !measure) return;

      const diff = measure.scrollWidth - container.clientWidth;

      setIsOverflowing(diff > 4);
      setDistance(Math.max(diff, 0));
    };

    checkOverflow();

    window.addEventListener("resize", checkOverflow);

    return () => {
      window.removeEventListener("resize", checkOverflow);
    };
  }, [text]);

  const duration = Math.min(Math.max(distance / 12, 7), 18);

  return (
    <div
      ref={containerRef}
      className={className}
      title={text}
      style={{
        width: "100%",
        overflow: "hidden",
        whiteSpace: "nowrap",
      }}
    >
      <span
        ref={measureRef}
        style={{
          position: "absolute",
          visibility: "hidden",
          whiteSpace: "nowrap",
          pointerEvents: "none",
        }}
      >
        {text}
      </span>

      {!isOverflowing && (
        <span
          style={{
            display: "block",
            overflow: "hidden",
            whiteSpace: "nowrap",
            textOverflow: "ellipsis",
          }}
        >
          {text}
        </span>
      )}

      {isOverflowing && (
        <span
          className="radioflix-scroll-title"
          style={
            {
              display: "inline-block",
              whiteSpace: "nowrap",
              "--scroll-distance": `${distance}px`,
              "--scroll-duration": `${duration}s`,
            } as React.CSSProperties
          }
        >
          {text}
        </span>
      )}

      <style jsx>{`
        .radioflix-scroll-title {
          animation: radioflix-title-scroll var(--scroll-duration) linear
            infinite alternate;
          animation-delay: 1.2s;
        }

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