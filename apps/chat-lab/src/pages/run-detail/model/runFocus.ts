import type { RunDetail, RunMetrics } from "@/shared/api/client";
import { formatCount, formatUsd } from "@/shared/lib/formatNumber";

import { REPLY_FLAG_LABELS } from "./detailLabels";

/** `warn` 은 호박(불일치·주의), `danger` 는 적색(깨짐), `quiet` 는 보조 글자색이다. */
export type FocusTone = "danger" | "warn" | "quiet";

export type FocusLine = {
  tone: FocusTone;
  text: string;
};

/**
 * 검사기 지표 탭 맨 위 "먼저 볼 것" — 런 상세와 런 지표 응답이 이미 센 값을 문장으로 묶기만 한다(새로 세지 않는다).
 *
 * 순서는 불일치 → 원가 빈칸·빠진 호출 → 짝 없는 기록 → 깨짐 → 나머지 플래그 → 응답 없는 턴 → 주의. 불일치와 주의는 따로 센다 —
 * 더하면 불일치 수가 정상 런과 어긋난 런을 가르지 못한다. 플래그 수에는 늘 표본 수를 붙인다(분모 없는 개수는 읽히지 않는다).
 * 아무것도 없으면 그렇다고 한 줄 적는다. 런 지표를 아직 받지 못했으면(받는 중·실패) 플래그는 모르는 것이라 "플래그 없음"이라고
 * 하지 않는다 — 그 사정은 지표 탭이 따로 적는다.
 */
export function describeRunFocus(detail: RunDetail, metrics: RunMetrics | undefined): FocusLine[] {
  const lines: FocusLine[] = [];
  const { cost } = detail;

  if (detail.mismatches.length > 0) {
    lines.push({ tone: "warn", text: `불일치 ${formatCount(detail.mismatches.length)}건 — 기록끼리 어긋난 자리가 있다.` });
  }
  if (cost === null) {
    lines.push({ tone: "quiet", text: "턴 기록 파일이 없어 토큰·원가가 비어 있다 — 턴 기록을 내보내면 채워진다." });
  } else {
    if (cost.unpricedCalls > 0) {
      lines.push({ tone: "quiet", text: `단가표에 없는 모델의 호출 ${formatCount(cost.unpricedCalls)}건이 원가 합에서 빠졌다.` });
    }
    if (cost.missingTokenCalls > 0) {
      lines.push({ tone: "quiet", text: `토큰이 기록되지 않은 호출 ${formatCount(cost.missingTokenCalls)}건이 있다.` });
    }
  }
  if (detail.unmatchedRows.length > 0) {
    const unmatchedUsd = cost === null ? "" : ` (${formatUsd(cost.unmatchedUsd)}, 런 원가에 넣지 않음)`;
    lines.push({
      tone: "quiet",
      text: `어느 시도에도 붙지 않은 턴 기록 행 ${formatCount(detail.unmatchedRows.length)}개${unmatchedUsd}.`,
    });
  }
  if (metrics !== undefined) {
    const sample = `표본 ${formatCount(metrics.scored)}턴`;
    if (metrics.broken > 0) {
      lines.push({ tone: "danger", text: `${REPLY_FLAG_LABELS.broken} ${formatCount(metrics.broken)} / ${sample}` });
    }
    const flagCounts = [
      ["truncated", metrics.truncated],
      ["selfCopy", metrics.selfCopy],
      ["labelLeak", metrics.labelLeak],
      ["userTurn", metrics.userTurn],
    ] as const;
    for (const [key, count] of flagCounts) {
      if (count > 0) lines.push({ tone: "quiet", text: `${REPLY_FLAG_LABELS[key]} ${formatCount(count)} / ${sample}` });
    }
    if (metrics.lost > 0) {
      lines.push({ tone: "quiet", text: `응답 없는 턴 ${formatCount(metrics.lost)}개 — 지표 표본에서 빠졌다.` });
    }
  }
  if (detail.cautions.length > 0) {
    lines.push({ tone: "warn", text: `주의 ${formatCount(detail.cautions.length)}건 — 불일치로 세지 않는 참고 사항이다.` });
  }
  if (lines.length > 0) return lines;
  return [{ tone: "quiet", text: metrics === undefined ? "불일치·주의 없음" : "불일치·주의 없음 · 플래그 없음" }];
}
