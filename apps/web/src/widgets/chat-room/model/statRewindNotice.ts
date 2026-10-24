import type { ChatRoomState, StatRewind } from "@/entities/chat-room";
import { assertNever } from "@/shared/lib/assertNever";

/** 안내를 고르는 데 쓰는 방의 사정. `hasStats` 는 보이는 스탯이 있는가다(숨긴 스탯은 방 스냅숏에서 빠진다). */
type RoomStatContext = { hasStats: boolean; hasReachedEnding: boolean };

/** 방 상태에서 안내 규칙이 보는 두 값을 뽑는다. 방을 아직 못 받았으면 둘 다 거짓이다. */
export function roomStatContext(room: ChatRoomState | undefined): RoomStatContext {
  return {
    hasStats: (room?.contentSnapshot?.stats.length ?? 0) > 0,
    hasReachedEnding: room?.endingStatus.reached ?? false,
  };
}

const ENDING_STAYS = "이미 본 엔딩은 그대로예요.";

/** 메시지를 지우거나 고친 뒤 스탯이 어떻게 됐는지 알리는 토스트 문구. 서버가 알릴 것이 없다고 했거나(사용자 메시지·오프닝·
 * 캐릭터 방, 또는 되돌리기 전의 서버) 보이는 스탯이 없는 방이면 띄우지 않는다 — 서버는 스탯이 없거나 숨긴 스탯뿐인 스토리 방에도
 * 값을 보내는데, 거기서 띄우면 잡음이고 숨긴 스탯이 있다는 것을 드러낸다. 엔딩은 되돌리지 않으므로 엔딩을 본 방에서 스탯을
 * 되돌렸을 때만 그 사실을 덧붙인다. `kept` 에는 이유를 대지 않는다: 중간 답 삭제 말고도 옛 삭제가 턴 수를 어긋나게 둔 방의
 * 마지막 답이 같은 값으로 온다. */
export function statRewindNotice(
  action: "delete" | "edit",
  statRewind: StatRewind | undefined,
  { hasStats, hasReachedEnding }: RoomStatContext,
): string | undefined {
  if (statRewind === undefined || !hasStats) return undefined;
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

/** 뒤 대화 여럿을 지우는 수정의 확인 창에 덧붙이는 스탯 줄. 토스트와 같은 규칙이다 — 보이는 스탯이 없으면 줄이 없고, 엔딩
 * 문장은 엔딩을 본 방에만 붙인다. */
export function editConfirmStatNote({ hasStats, hasReachedEnding }: RoomStatContext): string | undefined {
  if (!hasStats) return undefined;
  return hasReachedEnding ? `스탯은 지워지는 대화 전으로 돌아가요. ${ENDING_STAYS}` : "스탯은 지워지는 대화 전으로 돌아가요.";
}
