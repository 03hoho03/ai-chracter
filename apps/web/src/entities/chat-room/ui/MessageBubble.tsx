import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { MoreHorizontal, Pencil, RotateCw, Trash2 } from "lucide-react";

import type { ChatMessage } from "../api/chatStream";
import { ChatMarkdown } from "./ChatMarkdown";
import { MessageEditForm } from "./MessageEditForm";

type MessageBubbleProps = {
  message: ChatMessage;
  // 재생성/수정/삭제 액션. 세 콜백 모두 optional인 이유는 스트리밍 중 임시 버블
  // (streaming/ending-epilogue, ChatRoomView.tsx 참고)에는 실제 messageId가 없어 어떤 액션도
  // 붙일 수 없기 때문 — onDelete가 없으면 "⋯" 메뉴 자체를 렌더링하지 않는다.
  canRegenerate?: boolean;
  isEditing?: boolean;
  disabled?: boolean;
  onRegenerate?: () => void;
  onStartEdit?: () => void;
  onCancelEdit?: () => void;
  onSaveEdit?: (text: string) => void;
  onDelete?: () => void;
};

// 사용자 메시지 표시. 대화는 소설처럼 한 컬럼에 흐르고 사용자와 캐릭터 모두 상자 없는 산문이라,
// "지금 내가 한 말"은 채움이 아니라 왼쪽 1px 강조선과 그만큼의 들여쓰기로만 가른다. 수정 폼도 같은 틀을
// 써서 입력란이 원래 메시지 자리에 그대로 열린다.
const USER_MESSAGE_FRAME = "border-l border-primary pl-3";

export function MessageBubble({
  message,
  canRegenerate = false,
  isEditing = false,
  disabled = false,
  onRegenerate,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  if (isEditing) {
    return (
      <div className={cn(isUser && USER_MESSAGE_FRAME)}>
        <MessageEditForm content={message.content} onCancelEdit={onCancelEdit} onSaveEdit={onSaveEdit} />
      </div>
    );
  }

  return (
    <div className={cn("flex w-full flex-col gap-1.5", isUser && USER_MESSAGE_FRAME)}>
      {/* items-start — 산문이 여러 줄이 되면 "⋯" 메뉴가 items-end에서 문단 맨 아래로 밀려 첫 줄과
          멀어진다. 긴 메시지로 렌더해 대조한 결과 items-start가 메뉴를 첫 줄 옆에 고정해 자연스러웠다. */}
      <div className="flex items-start gap-1">
        {/* flex-1을 안 쓴 이유 — flex-basis:auto인 채로 max-w만 얹으면 짧은 메시지는 내용 폭만큼만
            차지하고(shrink-to-fit), 긴 메시지만 max-w 캡까지 늘어난다. flex-1(basis:0)을 쓰면 짧은
            메시지도 캡까지 강제로 늘어나 "⋯" 메뉴가 텍스트 끝에서 멀찍이 떨어진 채 뜬다(실측 확인).
            max-w-3xl(768px) — 1512px에서 문단이 폭 768px에서 멈추고 그 안의 줄들이 61~71자(LLM
            출력마다 줄바꿈이 달라진다)로 규범(65-75자) 안에 든다. 390px에서는 컬럼 폭 자체가 768px보다
            훨씬 좁아 캡이 걸리지 않는다. 사용자 메시지도 같은 캡이라 두 역할의 줄 길이가 같다. */}
        <ChatMarkdown content={message.content} className="max-w-3xl" />
        {onDelete && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="메시지 옵션"
                disabled={disabled}
                className="text-muted-foreground"
              >
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {canRegenerate && onRegenerate && (
                <DropdownMenuItem onSelect={onRegenerate}>
                  <RotateCw aria-hidden />
                  다시 생성
                </DropdownMenuItem>
              )}
              {onStartEdit && (
                <DropdownMenuItem onSelect={onStartEdit}>
                  <Pencil aria-hidden />
                  수정
                </DropdownMenuItem>
              )}
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 aria-hidden />
                삭제
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {!!message.imageUrl && (
        // 상황별 이미지는 원본 비율 그대로 보여준다(크롭 없음). 다만 그 비율을 미리 알 수 없어 이미지가
        // 도착한 뒤에야 높이가 정해지면 읽던 대화가 아래로 밀린다(CLS) → 고정 비율 자리를 먼저 깔고
        // 그 안에서 `object-contain`으로 맞춘다.
        //
        // 비율이 정사각이 아니라 3:4인 이유: 이 자리에 실제로 오는 상황별 이미지는 세로가 길다
        // (시드·생성물 모두 768x1024). 정사각 웰이면 세로 이미지의 높이가 칼럼 폭에 묶여
        // 모바일(343px 칼럼)에서 240x320 -> 193x257로 면적이 65%까지 줄었다(실측).
        //
        // 폭이 아니라 높이(`h-80`)를 고정한 이유: 폭을 고정하면 칼럼 너비에 따라 웰의 실제 비율이
        // 흔들려 레터박스가 생긴다. 높이를 못박으면 3:4 웰의 폭이 240px로 확정돼 어느 폭에서든
        // 240x320이 되고 레터박스도 없다. `max-w-3/4`는 칼럼이 320px보다 좁을 때만 걸리는 안전장치다.
        //
        // self-start — 부모가 items-* 없이 stretch라 그대로 두면 웰이 그 폭을 받아 aspect-ratio가
        // 무력화된다. stretch를 걷어 aspect-3/4+h-80이 실제 폭(240px)을 계산하게 한다.
        //
        // 상황별 이미지는 서버가 캐릭터 응답에만 붙인다. 역할로 가르지 않고 이미지가 있으면 그린다.
        <div className="self-start aspect-3/4 h-80 max-w-3/4 overflow-hidden rounded-lg bg-muted">
          <img
            src={message.imageUrl}
            alt="대화 중 노출된 이미지"
            loading="lazy"
            decoding="async"
            className="size-full object-contain"
          />
        </div>
      )}
    </div>
  );
}
