import type { ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import type { LucideIcon } from "lucide-react";

type MemoryNoteProps = {
  icon: LucideIcon;
  children: ReactNode;
  /** 읽어야 할 사실이면 본문 잉크로 올린다. 기본은 보조 안내의 흐린 잉크다. */
  isEmphasized?: boolean;
  className?: string;
};

/** 아이콘 하나와 짧은 문장 한 줄 — 목록 위 쓰임 표시와 확인 대화의 안내가 같은 모양을 쓴다. 상태는 색이 아니라 아이콘과
 * 문장이 가르고, 채움·테두리가 없다(목록과 대화 상자 안에서 상자를 겹치지 않으려고). */
export function MemoryNote({ icon: Icon, children, isEmphasized = false, className }: MemoryNoteProps) {
  return (
    <p
      className={cn(
        "flex gap-2 text-xs break-keep",
        isEmphasized ? "text-foreground" : "text-muted-foreground",
        className,
      )}
    >
      <Icon aria-hidden className="mt-px size-3.5 shrink-0 text-muted-foreground" />
      <span>{children}</span>
    </p>
  );
}
