import type { CallCostView } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/formatNumber";

import { describeTokenBar, type TokenPart } from "../model/tokenBar";

const PART_LABELS = {
  cacheRead: "캐시 읽기",
  cacheWrite: "캐시 쓰기",
  newInput: "새 입력",
  output: "출력",
} as const satisfies Record<TokenPart, string>;

/**
 * 토큰 막대 — 6px 높이 막대 하나에 캐시 읽기 · 캐시 쓰기 · 새 입력 · 출력 네 칸을 2px 틈으로 잇고, 칸 길이는 토큰 수에 비례한다.
 * 새 입력은 속을 비운 테두리 칸이다(옅은 선 색으로 채우면 면에 묻힌다). 코발트는 선택의 색이라 칸 색으로 쓰지 않는다. 막대 아래
 * 이름표에 칸마다 같은 모양의 견본·이름·숫자를 적어 색만으로 칸을 가리지 않는다. 토큰이 기록되지 않은 호출은 막대 대신 "기록 없음".
 */
export function TokenBar({ call }: { call: CallCostView }) {
  const bar = describeTokenBar(call);
  if (bar.kind === "missing") return <p className="mt-1.5 text-label text-ink-muted">토큰 기록 없음</p>;

  return (
    <div className="mt-1.5">
      <div
        role="img"
        aria-label={bar.segments.map((segment) => `${PART_LABELS[segment.part]} ${tokenText(segment.tokens)}`).join(", ")}
        className="flex h-1.5 gap-0.5"
      >
        {bar.segments
          .filter((segment) => segment.ratio > 0)
          .map((segment) => (
            <span
              key={segment.part}
              // 칸 길이는 토큰 수에 따라 달라지는 실행 중 값이다. 아주 작은 칸도 보이게 최소 2px.
              style={{ flexGrow: segment.ratio, flexBasis: 0 }}
              className={cn("min-w-0.5 rounded-xs", swatchClass(segment.part))}
            />
          ))}
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-2.5 gap-y-0.5 text-label text-ink-muted tabular-nums">
        {bar.segments.map((segment) => (
          <li key={segment.part} className="inline-flex items-center gap-1">
            <span aria-hidden="true" className={cn("inline-block h-1.5 w-2 rounded-xs", swatchClass(segment.part))} />
            {PART_LABELS[segment.part]}
            <span className={segment.tokens === undefined ? "text-ink-muted" : "text-ink-secondary"}>
              {tokenText(segment.tokens)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function tokenText(tokens: number | undefined): string {
  return tokens === undefined ? "기록 없음" : formatCount(tokens);
}

function swatchClass(part: TokenPart): string {
  switch (part) {
    case "cacheRead":
      return "bg-ink-muted";
    case "cacheWrite":
      return "bg-ink-secondary";
    case "newInput":
      return "border border-ink-muted";
    case "output":
      return "bg-ink";
    default:
      return assertNever(part);
  }
}
