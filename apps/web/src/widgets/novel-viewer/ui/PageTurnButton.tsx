import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";

type PageTurnButtonProps = {
  direction: "previous" | "next";
  /** 첫 화면의 이전·화 끝 화면의 다음처럼 더 갈 곳이 없다. */
  isBlocked: boolean;
  onTurn: () => void;
  className?: string;
  style?: CSSProperties;
};

/** 쪽 넘김 버튼(40px 누르는 면, 아이콘만). 막힌 쪽은 `aria-disabled` 다 — `disabled` 는 포커스를 빼앗아 키보드
 * 사용자가 자리를 잃는다(아래 바의 이전·다음 화 버튼과 같은 규칙). */
export function PageTurnButton({ direction, isBlocked, onTurn, className, style }: PageTurnButtonProps) {
  const Icon = direction === "previous" ? ChevronLeft : ChevronRight;

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-lg"
      aria-label={direction === "previous" ? "이전 쪽" : "다음 쪽"}
      aria-disabled={isBlocked}
      className={cn("aria-disabled:opacity-65", className)}
      style={style}
      onClick={() => {
        if (!isBlocked) onTurn();
      }}
    >
      <Icon aria-hidden className="size-6" />
    </Button>
  );
}
