import type { ChatRoomMemoryFact } from "@/entities/chat-room";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 사실 한 줄의 머리. 관계는 "주어 → 대상", 속성은 "주어 · 속성"이다. 짝이 비어 있으면 주어만 쓴다 — 서버는 종류에 맞는
 * 칸을 채우지만, 빈 짝을 화살표 뒤에 그대로 두면 "점장 → "처럼 끊긴 문장이 된다. */
export function factHeading(fact: Pick<ChatRoomMemoryFact, "kind" | "subject" | "object" | "attribute">): string {
  const other = fact.kind === "relation" ? fact.object : fact.attribute;
  if (!other) return fact.subject;
  return fact.kind === "relation" ? `${fact.subject} → ${other}` : `${fact.subject} · ${other}`;
}

/** 기억이 나온 대화 구간. 한 턴이면 한 번만 쓴다. */
export function turnRangeLabel(startTurn: number, endTurn: number): string {
  return startTurn === endTurn ? `${startTurn}번째 턴` : `${startTurn}~${endTurn}번째 턴`;
}

/** 탭 이름 옆 개수. 총계 API 가 없으니 다음 페이지가 남은 동안은 "+"를 붙여 불러온 만큼만 말한다. */
export function itemCountLabel(count: number, hasMore: boolean): string {
  return hasMore ? `${count}+` : `${count}`;
}

/** 이 방의 다음 응답에 그 기억이 실릴 수 있는가. 쓰이지 않아도 기억은 쌓인다는 것을 함께 말한다 — 쌓이지 않는다고 여기면
 * 지금 잊게 할 이유가 없어 보인다. */
export function usedInRepliesText(kind: "episodes" | "facts", isUsed: boolean): string {
  if (isUsed) return "이 대화방의 응답에 쓰이고 있어요.";
  return `지금은 응답에 쓰이지 않아요. ${kind === "episodes" ? "장면" : "사실"} 기억은 계속 쌓여요.`;
}

export function forgetSceneTitle(title: string): string {
  return `‘${title}’${koreanParticle(title, "을/를")} 잊게 할까요?`;
}

/** 사실 잊게 하기의 실행 버튼. 함께 지워질 장면이 있으면 그 수를 버튼에도 적는다 — 확인 문장만 읽지 않고 누르는 사람도
 * 무엇이 함께 사라지는지 알게. */
export function forgetFactConfirmLabel(episodeCount: number): string {
  return episodeCount > 0 ? `장면 ${episodeCount}개와 함께 잊게 하기` : "잊게 하기";
}

/** 두 확인 대화와 두 목록 끝에 함께 두는 안내 — 잊게 한 기억이 다시 생기는 길들. */
export const MEMORY_COMEBACK_NOTICE =
  "최근 대화나 앞으로의 대화에 같은 내용이 나오거나, 앞의 대화를 고치거나 지우거나 다시 생성하면 같은 기억이 다시 생길 수 있어요.";
