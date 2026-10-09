import type { AdminNovelDetailResponse } from "@/entities/admin-novel";

/** 독자에게 안 보이는 이유를 서버의 판정 재료(공개 상태·이용제한·게시자 정지·원작 상태·공개 화 수)에서 문장으로 푼다.
 * 여럿이 겹칠 수 있어 전부 낸다 — 운영자가 하나만 풀고 왜 아직 안 보이는지 헤매지 않게. */
export function hiddenReasons(novel: AdminNovelDetailResponse): string[] {
  if (novel.readable) return [];
  const reasons: string[] = [];
  if (novel.visibility === "withdrawn") reasons.push("게시자가 공개를 거뒀어요.");
  if (novel.moderationStatus === "restricted") reasons.push("운영자가 이용제한했어요.");
  if (novel.publisherSuspended) reasons.push("게시자가 이용정지 중이에요.");
  if (novel.sourceModerationStatus === null) reasons.push("원작이 지워졌어요.");
  else if (novel.sourceModerationStatus === "restricted") reasons.push("원작이 이용제한 중이에요.");
  else if (novel.sourceModerationStatus === "deleted") reasons.push("원작이 삭제됐어요.");
  if (novel.chapterCount === 0) reasons.push("공개된 화가 없어요.");
  return reasons.length > 0 ? reasons : ["독자에게 보이지 않는 상태예요."];
}
