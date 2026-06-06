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
  const [scrollDistance, setScrollDistance] = useState(0);

  useEffect(() => {
    const checkOverflow = () => {
      const container = containerRef.current;
      const measure = measureRef.current;

      if (!container || !measure) return;

      const distance = measure.scrollWidth - container.clientWidth;

      setIsOverflowing(distance > 4);
      setScrollDistance(Math.max(distance, 0));
    };

    checkOverflow();

    window.addEventListener("resize", checkOverflow);

    return () => {
      window.removeEventListener("resize", checkOverflow);
    };
  }, [text]);

  if (!isOverflowing) {
    return (
      <div
        ref={containerRef}
        className={`whitespace-nowrap overflow-hidden text-ellipsis ${className}`}
        title={text}
      >
        <span ref={measureRef}>{text}</span>
      </div>
    );
  }

  const duration = Math.min(Math.max(scrollDistance / 14, 6), 14);

  return (
    <div
      ref={containerRef}
      className={`relative whitespace-nowrap overflow-hidden ${className}`}
      title={text}
    >
      <span
        ref={measureRef}
        className="block overflow-hidden text-ellipsis whitespace-nowrap radioflix-title-ellipsis"
      >
        {text}
      </span>

      <span
        className="absolute left-0 top-0 inline-block pr-8 opacity-0 radioflix-title-scroll"
        style={
          {
            "--scroll-distance": `${scrollDistance}px`,
            "--scroll-duration": `${duration}s`,
          } as React.CSSProperties
        }
      >
        {text}
      </span>

      <style jsx>{`
        .radioflix-title-ellipsis {
          animation: radioflix-ellipsis-hide 1.2s ease forwards;
          animation-delay: 1.8s;
        }

        .radioflix-title-scroll {
          animation:
            radioflix-scroll-show 0.2s ease forwards 1.8s,
            radioflix-marquee var(--scroll-duration) linear 2s infinite alternate;
        }

        @keyframes radioflix-ellipsis-hide {
          from {
            opacity: 1;
          }
          to {
            opacity: 0;
          }
        }

        @keyframes radioflix-scroll-show {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }

        @keyframes radioflix-marquee {
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