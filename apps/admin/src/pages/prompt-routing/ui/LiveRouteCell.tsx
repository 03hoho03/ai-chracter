import {
  PROMPT_MODEL_LABELS,
  ROUTE_BACKEND_LABELS,
  ROUTE_SKIP_REASON_LABELS,
  ROUTE_SOURCE_LABELS,
  ROUTING_STAGE_LABELS,
  type AdminPromptRouteCell,
} from "@/entities/prompt-routing";

import { formatPrice } from "../model/describe";
import { NEUTRAL_BADGE_CLASS, PROBLEM_BADGE_CLASS } from "./badgeClasses";

type LiveRouteCellProps = {
  cell: AdminPromptRouteCell;
};

/** 마지막 저장 상태를 서버가 푼 값 그대로 보인다 — 폼을 고쳐도 바뀌지 않고, 출처·건너뛴 행도 화면이 다시 판단하지 않는다. */
export function LiveRouteCell({ cell }: LiveRouteCellProps) {
  const { effective, skipped } = cell;
  const call = cell.calls[0];
  const source =
    effective.source === "env" && effective.sourceDetail !== null
      ? `${ROUTE_SOURCE_LABELS.env} · ${effective.sourceDetail}`
      : ROUTE_SOURCE_LABELS[effective.source];

  return (
    <div className="flex min-w-56 flex-col gap-1 whitespace-normal">
      <span className="text-foreground">
        {PROMPT_MODEL_LABELS[effective.chainModel]} 체인 → {call?.modelId ?? PROMPT_MODEL_LABELS[effective.callModel]}
      </span>
      <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {ROUTE_BACKEND_LABELS[effective.backend]}
        <span className={NEUTRAL_BADGE_CLASS}>{source}</span>
      </span>
      {skipped !== null && (
        <span className="flex flex-col items-start gap-1 text-xs text-muted-foreground">
          <span className={PROBLEM_BADGE_CLASS}>적용 안 됨</span>
          <span className="break-keep">
            {skipped.stage === cell.stage ? "" : `${ROUTING_STAGE_LABELS[skipped.stage]} 행이 적용되지 않아요 — `}
            {ROUTE_SKIP_REASON_LABELS[skipped.reason]}: {skipped.message}
          </span>
        </span>
      )}
    </div>
  );
}

type LivePriceCellProps = {
  cell: AdminPromptRouteCell;
};

/** 채팅 호출의 단가를 두고, 미리보기 호출이 다른 모델로 가면 둘째 줄에 그 단가를 둔다. 단가 표에 없는 모델은 0 으로 보이지
 * 않게 "단가 표에 없음"이다. */
export function LivePriceCell({ cell }: LivePriceCellProps) {
  const [chat, preview] = cell.calls;
  if (chat === undefined) return <span className="text-muted-foreground">-</span>;

  return (
    <div className="flex flex-col gap-0.5 tabular-nums">
      <span className="text-foreground">{chat.price === null ? "단가 표에 없음" : formatPrice(chat.price)}</span>
      {preview !== undefined && (
        <span className="text-xs text-muted-foreground">
          {preview.modelId === chat.modelId
            ? "미리보기 같음"
            : `미리보기: ${preview.modelId} ${preview.price === null ? "단가 표에 없음" : formatPrice(preview.price)}`}
        </span>
      )}
    </div>
  );
}
