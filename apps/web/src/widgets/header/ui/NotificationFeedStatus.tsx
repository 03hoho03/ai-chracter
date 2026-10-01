import { Button } from "@ai-character-chat/ui/components/button";

type NotificationFeedStatusProps = {
  isPending: boolean; hasError: boolean; hasNext: boolean; isFetchingNext: boolean; onRetry: () => void; onMore: () => void;
};

export function NotificationFeedStatus({ isPending, hasError, hasNext, isFetchingNext, onRetry, onMore }: NotificationFeedStatusProps) {
  return <div className="flex flex-col items-start gap-2 px-2 py-2">
    {isPending && <p role="status" className="text-xs text-muted-foreground">알림을 불러오는 중…</p>}
    {hasError && <><p role="alert" className="break-keep text-xs text-destructive-text">알림을 불러오지 못했어요.</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>다시 시도</Button></>}
    {hasNext && <Button type="button" variant="outline" size="sm" aria-disabled={isFetchingNext}
      className="aria-disabled:opacity-65" onClick={() => { if (!isFetchingNext) onMore(); }}>
      {isFetchingNext ? "불러오는 중…" : "알림 더 보기"}</Button>}
  </div>;
}
