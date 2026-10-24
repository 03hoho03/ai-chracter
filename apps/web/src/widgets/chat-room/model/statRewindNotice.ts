import type { StatRewind } from "@/entities/chat-room";
import { assertNever } from "@/shared/lib/assertNever";

const ENDING_STAYS = "이미 본 엔딩은 그대로예요.";

/** 메시지를 지우거나 고친 뒤 스탯이 어떻게 됐는지 알리는 토스트 문구. 서버가 알릴 것이 없다고 했으면(사용자 메시지·오프닝·
 * 스탯 없는 방, 또는 되돌리기 전의 서버) 띄우지 않는다. 엔딩은 되돌리지 않으므로 엔딩을 본 방에서 스탯을 되돌렸을 때만 그
 * 사실을 덧붙인다 — 엔딩이 없는 방에서는 잡음이다. `kept` 에는 이유를 대지 않는다: 중간 답 삭제 말고도 옛 삭제가 턴 수를
 * 어긋나게 둔 방의 마지막 답이 같은 값으로 온다. */
export function statRewindNotice(
  action: "delete" | "edit",
  statRewind: StatRewind | undefined,
  hasReachedEnding: boolean,
): string | undefined {
  if (statRewind === undefined) return undefined;
  const done = action === "delete" ? "메시지를 지웠어요." : "메시지를 고쳤어요.";
  switch (statRewind) {
    case "rewound":
      if (action === "delete") {
        return `${done} 스탯도 그 답 전으로 되돌렸어요.${hasReachedEnding ? ` ${ENDING_STAYS}` : ""}`;
      }
      return hasReachedEnding
        ? `${done} 스탯을 고친 턴 전으로 되돌렸고, ${ENDING_STAYS}`
        : `${done} 스탯도 고친 턴 전으로 되돌렸어요.`;
    case "partial":
      return action === "delete"
        ? `${done} 오래된 대화라 이 답의 스탯은 되돌리지 못했어요.`
        : `${done} 오래된 대화가 섞여 있어 그 부분의 스탯은 되돌리지 못했어요.`;
    case "kept":
      return `${done} 스탯은 되돌리지 않아요.`;
    default:
      return assertNever(statRewind);
  }
}
