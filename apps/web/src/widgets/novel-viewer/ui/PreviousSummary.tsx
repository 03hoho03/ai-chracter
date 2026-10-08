import { ChevronDown } from "lucide-react";

/** 이전 줄거리 — 바로 앞 화의 요약 하나를 접어 둔다. 이어 읽는 사람만 펼치면 되므로 기본은 닫힘이고, 열고 닫기는
 * `<details>` 의 기본 동작에 맡긴다(키보드·보조기기 지원이 따라온다). 상자는 채움 없이 윤곽만이다. */
export function PreviousSummary({ ordinal, summary }: { ordinal: number; summary: string }) {
  return (
    <details className="group rounded-xl border border-border px-4 py-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md text-sm font-medium text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        이전 줄거리 · {ordinal}화
        <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground group-open:rotate-180 motion-safe:transition-transform" />
      </summary>
      <p className="pt-2 text-sm whitespace-pre-line text-pretty break-keep text-muted-foreground">{summary}</p>
    </details>
  );
}
