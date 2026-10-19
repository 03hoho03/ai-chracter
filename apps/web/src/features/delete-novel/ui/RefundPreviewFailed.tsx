import { Button } from "@ai-character-chat/ui/components/button";

/** 정책 스위치가 켜졌는데 삭제 전 확인 값을 받지 못했을 때 환급 고지 상자 자리에 둔다 — 지우기는 막혀 있고, 다시 받으면
 * 맞는 안내로 바뀐다. */
export function RefundPreviewFailed({ isRetrying, onRetry }: { isRetrying: boolean; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2">
      <p className="text-sm break-keep text-destructive-text">
        노벨에서 소장한 회원이 있는지 확인하지 못해 지금은 지울 수 없어요. 잠시 후 다시 시도해주세요.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={isRetrying}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isRetrying) return;
          onRetry();
        }}
      >
        다시 시도
      </Button>
    </div>
  );
}
