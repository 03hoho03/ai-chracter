import { useId, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { Info } from "lucide-react";

import { shouldConfirmEditTruncation } from "../model/editTruncation";

type MessageEditFormProps = {
  content: string;
  /** 저장하면 지워질 뒤 메시지 수. 확인받을 만큼이면 입력란 아래에 미리 알린다(확인 자체는 저장을 받는 쪽이 한다). */
  removedMessageCount?: number;
  onCancelEdit?: () => void;
  onSaveEdit?: (text: string) => void;
};

// 편집 시작 시 원문으로 초기화해야 하는 draft는 prop 동기화 effect가 아니라, 편집 진입 시에만
// 마운트되는 이 컴포넌트의 useState 초기값으로 만든다(MessageBubble이 isEditing 분기로 이 컴포넌트를
// 통째로 마운트/언마운트한다).
export function MessageEditForm({ content, removedMessageCount = 0, onCancelEdit, onSaveEdit }: MessageEditFormProps) {
  const [draft, setDraft] = useState(content);
  const trimmed = draft.trim();
  const truncationNoticeId = useId();
  const hasTruncationNotice = shouldConfirmEditTruncation(removedMessageCount);

  return (
    // 폭은 메시지 본문과 같은 캡(max-w-3xl)이라 입력란이 원래 메시지 자리를 그대로 덮는다. 버튼은 입력란 오른쪽
    // 끝 아래에 붙인다.
    <div className="flex w-full max-w-3xl flex-col items-end gap-1.5">
      <Textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (trimmed) onSaveEdit?.(trimmed);
          } else if (event.key === "Escape") {
            onCancelEdit?.();
          }
        }}
        autoFocus
        rows={2}
        className="resize-none"
        aria-describedby={hasTruncationNotice ? truncationNoticeId : undefined}
      />
      {/* 저장을 누르기 전에 무엇이 지워지는지 보이게 한다 — 확인창에서 처음 알게 되면 이미 고쳐 쓴 뒤다. */}
      {hasTruncationNotice && (
        <p id={truncationNoticeId} className="flex items-start gap-1.5 self-stretch text-xs break-keep text-muted-foreground">
          <Info aria-hidden className="mt-px size-3.5 shrink-0" />
          저장하면 아래 메시지 {removedMessageCount}개가 지워지고 새 답을 받아요
        </p>
      )}
      <div className="flex gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancelEdit}>
          취소
        </Button>
        <Button type="button" size="sm" disabled={!trimmed} onClick={() => onSaveEdit?.(trimmed)}>
          저장
        </Button>
      </div>
    </div>
  );
}
