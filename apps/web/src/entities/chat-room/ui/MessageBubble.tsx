import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { MoreHorizontal, Pencil, RotateCw, Trash2 } from "lucide-react";

import type { ChatMessage } from "../api/chatStream";
import { MessageEditForm } from "./MessageEditForm";

type MessageBubbleProps = {
  message: ChatMessage;
  // US-077 — 재생성/수정/삭제 액션. 세 콜백 모두 optional인 이유는 스트리밍 중 임시 버블
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
    return <MessageEditForm content={message.content} onCancelEdit={onCancelEdit} onSaveEdit={onSaveEdit} />;
  }

  // design-system-progress.md P-4 / design-system-goal-prompt.md D-6 — assistant는 말풍선 상자를
  // 벗기고 전폭 산문으로, user는 bg-primary 말풍선을 유지한다(One-Accent Rule의 "지금 내가 한 말").
  // 두 갈래가 items-end/items-start·flex-row-reverse·이미지 웰 정렬까지 전부 달라 return 자체를
  // 갈랐다 — 조건부 className만 바꾸면 assistant 쪽이 여전히 shrink-to-fit으로 남는다.
  if (isUser) {
    return (
      <div className="flex flex-col items-end gap-1.5">
        <div className="flex flex-row-reverse items-end gap-1">
          <p className="max-w-3/4 whitespace-pre-wrap break-words break-keep rounded-lg bg-primary px-3.5 py-2.5 text-sm leading-relaxed text-primary-foreground">
            {message.content}
          </p>
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
              <DropdownMenuContent align="end">
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
          // US-073/US-014 — 상황별 이미지는 원본 비율 그대로 보여준다(크롭 없음). 다만 그 비율을
          // 미리 알 수 없어 이미지가 도착한 뒤에야 높이가 정해지면 읽던 대화가 아래로 밀린다(CLS) →
          // 고정 비율 자리를 먼저 깔고 그 안에서 `object-contain`으로 맞춘다.
          //
          // 비율이 정사각이 아니라 3:4인 이유: 이 자리에 실제로 오는 상황별 이미지는 세로가 길다
          // (시드·생성물 모두 768x1024). 정사각 웰이면 세로 이미지의 높이가 칼럼 폭에 묶여
          // 모바일(343px 칼럼)에서 240x320 -> 193x257로 면적이 65%까지 줄었다(실측).
          //
          // 폭이 아니라 높이(`h-80`)를 고정한 이유: 폭을 고정하면 칼럼 너비에 따라 웰의 실제 비율이
          // 흔들려 레터박스가 생긴다. 높이를 기존 상한(max-h-80)과 같은 값으로 못박으면 3:4 웰의
          // 폭이 240px로 확정돼, 어느 폭에서든 기존과 정확히 같은 240x320이 되고 레터박스도 없다.
          // `max-w-3/4`는 칼럼이 320px보다 좁을 때만 걸리는 안전장치(기존 제약과 동일).
          // items-end(부모)가 이 웰의 우측 정렬도 함께 지므로 여기선 손댈 필요가 없다.
          <div className="aspect-3/4 h-80 max-w-3/4 overflow-hidden rounded-lg bg-muted">
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

  return (
    <div className="flex w-full flex-col gap-1.5">
      {/* items-start(원래는 items-end) — 산문이 여러 줄이 되면 "⋯" 메뉴가 items-end에서 문단 맨
          아래로 밀려 첫 줄과 멀어진다(design-system-goal-prompt.md §4-3 D-6 지적). 실제 긴 메시지로
          렌더해 대조한 결과 items-start가 메뉴를 첫 줄 옆에 고정해 훨씬 자연스러웠다 — 채택. */}
      <div className="flex items-start gap-1">
        {/* flex-1을 안 쓴 이유 — flex-basis:auto인 채로 max-w만 얹으면 짧은 메시지는 원래
            말풍선처럼 내용 폭만큼만 차지하고(shrink-to-fit), 긴 메시지만 max-w 캡까지 늘어난다.
            flex-1(basis:0)을 쓰면 짧은 메시지도 캡까지 강제로 늘어나 "⋯" 메뉴가 텍스트 끝에서
            멀찍이 떨어진 채 뜬다(실측 확인) — 그래서 뺐다. min-w-0은 sibling 버튼과 함께 있을 때
            flex item의 기본 min-width:auto가 줄바꿈을 막는 것을 방지하는 안전장치.
            max-w-3xl(768px, D-10) — 1512px에서 실제 렌더 실측 결과 assistant 문단이 폭 768px에서
            멈추고 그 안의 줄들이 61~71자(샘플에 따라 변동, LLM 출력마다 줄바꿈이 달라진다)로
            규범(65-75자) 안에 든다(design-system-progress.md P-4-4b). 390px에서는 컬럼 폭 자체가
            768px보다 훨씬 좁아 캡이 전혀 걸리지 않는다 — `globals.css`엔 `prose` 유틸리티가 없고
            이 한 줄짜리 값이면 충분해 새 토큰을 만들지 않았다. */}
        <p className="min-w-0 max-w-3xl whitespace-pre-wrap break-words break-keep text-sm leading-relaxed text-foreground">
          {message.content}
        </p>
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
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 aria-hidden />
                삭제
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {!!message.imageUrl && (
        // 부모가 이제 items-* 없이 stretch라 이 웰도 그 폭을 그대로 받아 aspect-ratio가 무력화된다
        // (design-system-goal-prompt.md §4-3 D-6 표 — "이미지 웰, 놓치기 쉬운 지점"). self-start로
        // stretch를 걷어 아래 aspect-3/4+h-80이 실제 폭(240px)을 계산하게 하고 좌측 정렬도 되살린다.
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
