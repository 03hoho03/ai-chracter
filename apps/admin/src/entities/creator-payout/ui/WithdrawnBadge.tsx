import { cn } from "@ai-character-chat/ui/lib/utils";

/**
 * 수취인이 탈퇴했다는 표식. 처리 방법이 달라지는 사실이라(반려 대신 보류·수취 정보 교체) 목록과 상세 어디서나 같은 모양으로
 * 보인다. 상태 배지 관례대로 채움 없는 윤곽이고, 운영자가 봐야 할 상태라 잉크는 `foreground` 로 올린다.
 */
export function WithdrawnBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-foreground",
        className,
      )}
    >
      탈퇴
    </span>
  );
}
