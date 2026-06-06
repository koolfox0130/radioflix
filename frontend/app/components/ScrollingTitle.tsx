"use client";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const length = Array.from(text).length;

  // この文字数を超えたら必ずスクロール
  const shouldScroll = length >= 11;

  if (!shouldScroll) {
    return (
      <div
        className={`w-full overflow-hidden whitespace-nowrap text-ellipsis ${className}`}
        title={text}
      >
        {text}
      </div>
    );
  }

  return (
    <div
      className={`relative w-full overflow-hidden whitespace-nowrap ${className}`}
      title={text}
    >
      <div className="radioflix-marquee-title inline-block whitespace-nowrap pr-8">
        {text}
      </div>

      <style jsx>{`
        .radioflix-marquee-title {
          animation: radioflix-marquee-title 12s ease-in-out infinite;
          animation-delay: 1s;
        }

        @keyframes radioflix-marquee-title {
          0% {
            transform: translateX(0);
          }

          20% {
            transform: translateX(0);
          }

          70% {
            transform: translateX(-55%);
          }

          100% {
            transform: translateX(0);
          }
        }
      `}</style>
    </div>
  );
}