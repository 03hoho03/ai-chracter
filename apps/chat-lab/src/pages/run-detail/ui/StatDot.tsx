import { assertNever } from "@/shared/lib/assertNever";
import { cn } from "@/shared/lib/cn";

import type { StatTone } from "../model/turnRows";

/**
 * 스탯을 가리키는 6px 점. 보이는 스탯은 타임라인 선 색, 선이 없는 넷째부터는 보조 글자색, 숨김 스탯은 네 번째 색을 얻지 않고
 * 흐린 글자색 고리다. 색만으로 뜻을 싣지 않도록 쓰는 쪽이 이름·값을 글로 함께 둔다.
 */
export function StatDot({ tone }: { tone: StatTone }) {
  return <span aria-hidden="true" className={cn("inline-block size-1.5 shrink-0 rounded-full", toneClass(tone))} />;
}

function toneClass(tone: StatTone): string {
  switch (tone) {
    case "series-1":
      return "bg-series-1";
    case "series-2":
      return "bg-series-2";
    case "series-3":
      return "bg-series-3";
    case "other":
      return "bg-ink-secondary";
    case "hidden":
      return "border border-ink-muted";
    default:
      return assertNever(tone);
  }
}
