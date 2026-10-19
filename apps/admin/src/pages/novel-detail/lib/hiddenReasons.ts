import type { AdminNovelDetailResponse } from "@/entities/admin-novel";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

/** 독자에게 안 보이는 이유를 서버의 판정 재료(숨김·공개 상태·첫 공개 심사·이용제한·게시자 정지·원작 상태·공개 화 수)에서 문장으로 푼다.
 * 여럿이 겹칠 수 있어 전부 낸다 — 운영자가 하나만 풀고 왜 아직 안 보이는지 헤매지 않게. */
export function hiddenReasons(novel: AdminNovelDetailResponse): string[] {
  if (novel.readable) return [];
  const reasons: string[] = [];
  // 판매된 소설을 게시자가 지우면 지우지 않고 숨긴다(공개 범위도 `withdrawn`). 승인 대기·반려 행도 공개 범위가 `withdrawn`
  // 이다. 그래서 숨김·심사를 먼저 가른다 — 게시자가 거둔 것으로 읽히면 운영자가 할 일을 놓친다. 숨김 시각이 없으면(옛
  // 서버) 숨김은 가르지 않는다.
  if (typeof novel.hiddenAt === "string") {
    reasons.push(`게시자가 지웠지만 소장한 회원이 있어 숨겨 뒀어요(${formatDateTime(novel.hiddenAt)}).`);
  } else if (novel.reviewStatus === "pending") reasons.push("첫 공개가 운영자 승인을 기다리고 있어요.");
  else if (novel.reviewStatus === "rejected") reasons.push("운영자가 첫 공개를 반려했어요.");
  else if (novel.visibility === "withdrawn") reasons.push("게시자가 공개를 거뒀어요.");
  if (novel.moderationStatus === "restricted") reasons.push("운영자가 이용제한했어요.");
  if (novel.publisherSuspended) reasons.push("게시자가 이용정지 중이에요.");
  if (novel.sourceModerationStatus === null) reasons.push("원작이 지워졌어요.");
  else if (novel.sourceModerationStatus === "restricted") reasons.push("원작이 이용제한 중이에요.");
  else if (novel.sourceModerationStatus === "deleted") reasons.push("원작이 삭제됐어요.");
  if (novel.chapterCount === 0) reasons.push("공개된 화가 없어요.");
  return reasons.length > 0 ? reasons : ["독자에게 보이지 않는 상태예요."];
}
