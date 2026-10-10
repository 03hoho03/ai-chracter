import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";

import { RoomChatModelModal } from "./RoomChatModelModal";

type ChatModelChipProps = {
  roomId: string;
  modelName: string;
  /** `header` 는 채팅 헤더 한 줄(sm 이상), `input-bar` 는 좁은 화면에서 입력 바의 클로버 잔량 줄 왼쪽(sm 미만)이다. */
  placement: "header" | "input-bar";
};

const PLACEMENT_CLASS: Record<ChatModelChipProps["placement"], string> = {
  // 터치 기기 40px 도 이름 열 두 줄(약 41.5px)보다 낮아 헤더 높이가 그대로다.
  header: "hidden sm:inline-flex pointer-coarse:h-10",
  // 입력 바 줄은 높이를 키우지 않고 터치 영역만 의사요소로 위아래로 넓힌다.
  "input-bar": "relative sm:hidden pointer-coarse:after:absolute pointer-coarse:after:-inset-y-1 pointer-coarse:after:inset-x-0",
};

/** 지금 이 방이 어느 모델로 답을 쓰는지 보여 주고, 누르면 모델 선택 모달을 연다(⋮ 패널의 「AI 모델」과 같은 모달).
 *
 * 클릭 칩인데 secondary 가 아니라 outline pill 인 이유: 좁은 화면에서 이 칩은 추천 답변 칩(secondary pill) 바로 아래
 * 놓여, 같은 모양이면 답변 후보 하나로 읽힌다. 누를 수 있어 보더는 input 이고, 글자는 상위 모델이어도 muted 다 —
 * 턴마다 클로버가 나가는 상태는 입력 바의 클로버 잔량이 늘 보여 준다.
 *
 * 접근 이름은 보이는 이름 앞뒤에 sr-only 조각을 덧붙여 "AI 모델 {이름}, 바꾸기"로 만든다 — `aria-label` 로 덮으면 보이는
 * 글자와 읽는 이름이 갈린다. */
export function ChatModelChip({ roomId, modelName, placement }: ChatModelChipProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-haspopup="dialog"
      onClick={() => void RoomChatModelModal.call({ roomId })}
      className={cn("max-w-48 rounded-full text-muted-foreground", PLACEMENT_CLASS[placement])}
    >
      <span className="sr-only">AI 모델 </span>
      <span className="min-w-0 truncate">{modelName}</span>
      <span className="sr-only">, 바꾸기</span>
      <ChevronDown data-icon="inline-end" aria-hidden />
    </Button>
  );
}
