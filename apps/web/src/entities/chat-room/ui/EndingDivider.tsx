import { Sparkles } from "lucide-react";

// 엔딩 도달을 알리는 구분선. 바로 아래 오는 에필로그 메시지(MessageBubble — 일반 캐릭터 메시지와 같은
// 컬럼에 같은 상자 없는 산문으로 그려진다)와 짝을 이뤄, 그 메시지가 엔딩임을 표시하는 역할만 한다.
export function EndingDivider({ endingName }: { endingName?: string }) {
  return (
    <div role="separator" aria-label="엔딩 도달" className="flex items-center gap-3 py-1">
      <div className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">
        <Sparkles aria-hidden className="size-3.5" />
        {endingName ? `엔딩 · ${endingName}` : "엔딩에 도달했어요"}
      </span>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}
