"use client";

type Props = {
  text: string;
  className?: string;
};

export default function ScrollingTitle({ text, className = "" }: Props) {
  const length = Array.from(text).length;

  // 11文字以上ならスクロール対象
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
      className={`w-full overflow-hidden whitespace-nowrap ${className}`}
      title={text}
    >
      <span className="radioflix-marquee-title inline-block whitespace-nowrap">
        {text}
      </span>
    </div>
  );
}