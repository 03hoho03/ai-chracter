import type { RunListItem } from "@/shared/api/client";
import { OLD_FORMAT_EXPORT_REASON, runRecordGap } from "@/shared/api/recordGap";

/** `warn` 은 호박(불일치·주의), `danger` 는 적색(열 수 없음), `quiet` 는 보조 글자색이다. */
export type AttentionTone = "danger" | "warn" | "quiet";

export type Attention = {
  tone: AttentionTone;
  text: string;
};

/**
 * 미리보기 맨 위 "먼저 볼 것" 문장들 — 목록 한 줄의 칸만으로 만든다(상세를 따로 부르지 않는다).
 *
 * 순서는 열 수 없음 → 불일치 → 원가 빈칸 → 단가 없는 호출 → 주의. 불일치와 주의는 따로 센다 — 주의는 결합이 어긋났다고 보지
 * 않는 참고 사항이라, 더하면 불일치 수가 정상 런과 어긋난 런을 가르지 못한다. 아무것도 없으면 그렇다고 한 줄 적는다.
 */
export function describeAttention(item: RunListItem): Attention[] {
  if (item.openError != null) return [{ tone: "danger", text: `열 수 없다 — ${item.openError}` }];
  if (!item.supported) {
    return [{ tone: "danger", text: "지원하지 않는 옛 형식이라 열지 않는다 — 드라이버 턴 줄에 방 id 가 없다." }];
  }

  const lines: Attention[] = [];
  const mismatchCount = item.mismatchCount ?? 0;
  const cautionCount = item.cautionCount ?? 0;
  const unpricedCalls = item.unpricedCalls ?? 0;

  if (mismatchCount > 0) {
    lines.push({ tone: "warn", text: `불일치 ${mismatchCount}건 — 기록끼리 어긋난 자리가 있다. 상세에서 먼저 본다.` });
  }
  if (runRecordGap(item) === "oldFormat") {
    lines.push({ tone: "quiet", text: `이전 형식이라 토큰·원가가 없다 — ${OLD_FORMAT_EXPORT_REASON}.` });
  } else if (item.costUsd == null) {
    lines.push({ tone: "quiet", text: "턴 기록 파일이 없어 토큰·원가가 비어 있다 — 상세에서 턴 기록을 내보내면 채워진다." });
  }
  if (unpricedCalls > 0) {
    lines.push({ tone: "quiet", text: `단가표에 없는 모델의 호출 ${unpricedCalls}건이 원가 합에서 빠졌다.` });
  }
  if (cautionCount > 0) {
    lines.push({ tone: "warn", text: `주의 ${cautionCount}건 — 불일치로 세지 않는 참고 사항이다.` });
  }
  return lines.length > 0 ? lines : [{ tone: "quiet", text: "불일치·주의 없음" }];
}
