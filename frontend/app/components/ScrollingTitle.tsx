"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const measureRef = useRef<HTMLSpanElement | null>(null);

  const [shouldScroll, setShouldScroll] = useState(false);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const check = () => {
      const container = containerRef.current;
      const measure = measureRef.current;

      if (!container || !measure) return;

      const containerWidth = container.clientWidth;
      const textWidth = measure.scrollWidth;
      const diff = textWidth - containerWidth;

      setShouldScroll(diff > 8);
      setDistance(Math.max(diff + 32, 0));
    };

    check();

    const timer1 = setTimeout(check, 300);
    const timer2 = setTimeout(check, 1000);

    window.addEventListener("resize", check);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      window.removeEventListener("resize", check);
    };
  }, [text]);

  const duration = Math.min(Math.max(distance / 10, 8), 22);

  return (
    <>
      <div
        ref={containerRef}
        className={`relative w-full overflow-hidden whitespace-nowrap ${className}`}
        title={text}
      >
        {!shouldScroll && (
          <span className="block w-full overflow-hidden whitespace-nowrap text-ellipsis">
            {text}
          </span>
        )}

        {shouldScroll && (
          <>
            <span className="block w-full overflow-hidden whitespace-nowrap text-ellipsis radioflix-title-ellipsis">
              {text}
            </span>

            <span
              className="absolute left-0 top-0 inline-block whitespace-nowrap opacity-0 radioflix-title-scroll"
              style={
                {
                  "--scroll-distance": `${distance}px`,
                  "--scroll-duration": `${duration}s`,
                } as React.CSSProperties
              }
            >
              {text}
            </span>
          </>
        )}
      </div>

      <span
        ref={measureRef}
        className={className}
        style={{
          position: "fixed",
          left: "-99999px",
          top: "-99999px",
          whiteSpace: "nowrap",
          visibility: "hidden",
          pointerEvents: "none",
        }}
      >
        {text}
      </span>

      <style jsx>{`
        .radioflix-title-ellipsis {
          animation: radioflix-hide-ellipsis 0.2s ease forwards;
          animation-delay: 1.8s;
        }

        .radioflix-title-scroll {
          animation:
            radioflix-show-scroll 0.2s ease forwards 1.8s,
            radioflix-title-marquee var(--scroll-duration) ease-in-out 2s infinite alternate;
        }

        @keyframes radioflix-hide-ellipsis {
          from {
            opacity: 1;
          }
          to {
            opacity: 0;
          }
        }

        @keyframes radioflix-show-scroll {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }

        @keyframes radioflix-title-marquee {
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
    </>
  );
}