import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";

type MessageEditFormProps = {
  content: string;
  onCancelEdit?: () => void;
  onSaveEdit?: (text: string) => void;
};

// STATE-06 — 편집 시작 시 원문으로 초기화해야 하는 draft는 prop 동기화 effect가 아니라, 편집 진입 시에만
// 마운트되는 이 컴포넌트의 useState 초기값으로 만든다(MessageBubble이 isEditing 분기로 이 컴포넌트를
// 통째로 마운트/언마운트한다).
export function MessageEditForm({ content, onCancelEdit, onSaveEdit }: MessageEditFormProps) {
  const [draft, setDraft] = useState(content);
  const trimmed = draft.trim();

  return (
    <div className="flex flex-col items-end gap-1.5">
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
        className="max-w-3/4 resize-none"
      />
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
