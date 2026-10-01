import { useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Flag, MoreHorizontal, Pencil, RotateCw, Trash2 } from "lucide-react";

import { MediaImageFrame } from "@/shared/ui/media-image-frame/MediaImageFrame";

import type { ChatMessage } from "../api/chatStream";
import { ChatMarkdown } from "./ChatMarkdown";
import { MessageEditForm } from "./MessageEditForm";

type MessageBubbleProps = {
  message: ChatMessage;
  // 재생성/수정/신고/삭제 액션. 모두 optional인 이유는 스트리밍 중 임시 버블
  // (streaming/ending-epilogue, ChatRoomView.tsx 참고)에는 실제 messageId가 없어 어떤 액션도
  // 붙일 수 없기 때문 — onDelete·onReport가 둘 다 없으면 "⋯" 메뉴 자체를 렌더링하지 않는다.
  canRegenerate?: boolean;
  isEditing?: boolean;
  disabled?: boolean;
  onRegenerate?: () => void;
  onStartEdit?: () => void;
  onCancelEdit?: () => void;
  onSaveEdit?: (text: string) => void;
  onDelete?: () => void;
  // 신고 모달은 라우트 루트에 마운트돼 이 버블 밖에서 열리므로, 닫힌 뒤 포커스를 이 "⋯" 트리거로
  // 돌려줄 함수를 함께 넘긴다(안 그러면 포커스가 `<body>`로 떨어져 Tab이 헤더부터 다시 시작한다).
  onReport?: (returnFocus: () => void) => void;
};

// 사용자 메시지 표시. 대화는 소설처럼 한 컬럼에 흐르고 사용자와 캐릭터 모두 상자 없는 산문이라,
// "지금 내가 한 말"은 채움이 아니라 왼쪽 1px 강조선과 그만큼의 들여쓰기로만 가른다. 수정 폼도 같은 틀을
// 써서 입력란이 원래 메시지 자리에 그대로 열린다. 작성 가이드의 대화 예시도 이 틀을 그대로 쓴다 — 가이드가
// 보여 주는 모양이 실제 채팅 화면과 어긋나지 않게 하려고 클래스를 베끼지 않고 공개한다.
export const USER_MESSAGE_FRAME = "border-l border-primary pl-3";

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
  onReport,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const menuTriggerRef = useRef<HTMLButtonElement>(null);

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
        {(onDelete || onReport) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                ref={menuTriggerRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="메시지 옵션"
                disabled={disabled}
                // 24px는 마우스로는 충분하지만 손가락으로는 본문을 함께 누르기 쉽다 — 터치 기기에서만 32px.
                className="text-muted-foreground pointer-coarse:size-8"
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
              {/* 신고는 데이터를 지우지 않으므로 destructive가 아니다. 파괴 항목(삭제)을 맨 끝에 두려고 그 앞에 놓는다. */}
              {onReport && (
                <DropdownMenuItem onSelect={() => onReport(() => menuTriggerRef.current?.focus())}>
                  <Flag aria-hidden />
                  신고
                </DropdownMenuItem>
              )}
              {onDelete && (
                <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                  <Trash2 aria-hidden />
                  삭제
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {!!message.imageUrl && (
        // 판정 이미지는 본문 아래 블록이다. 크기를 아는 그림(스토리 미디어 북)은 원본 비율로, 모르는 그림(캐릭터
        // 상황별 이미지 — 서버가 크기를 싣지 않는다)은 지금까지와 같은 3:4 웰로 그린다. 두 갈래 모두 그림이 오기 전에
        // 높이를 잡는다(규칙은 `MediaImageFrame`). 역할로 가르지 않고 이미지가 있으면 그린다.
        <MediaImageFrame
          url={message.imageUrl}
          width={message.imageWidth}
          height={message.imageHeight}
          alt="대화 중 노출된 이미지"
          // 채팅방·미리보기 화면의 페이지 배경 위다(메시지 틀에는 면이 없다).
          surface="muted"
        />
      )}
    </div>
  );
}
