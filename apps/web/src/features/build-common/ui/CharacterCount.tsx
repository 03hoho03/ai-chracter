import { cn } from "@ai-character-chat/ui/lib/utils";
import type { ReactNode } from "react";

type CharacterCountProps = {
  /** 입력칸의 `aria-describedby` 가 가리킬 id. */
  id: string;
  /** 코드 포인트로 센 글자 수(`shared/lib/text/characterCount`). */
  count: number;
  max: number;
  /** 방금 입력이 상한에서 잘렸는가. 그 순간에만 도움말 자리에 알린다. */
  isTruncated?: boolean;
  /** 입력칸 아래 도움말. 잘렸다는 알림이 뜨는 동안은 그 자리를 비켜 준다. */
  help?: ReactNode;
};

/**
 * 글자 수 상한이 있는 빌더 입력칸 바로 아래 줄 — 왼쪽은 도움말, 오른쪽은 `n/최대`. 상한에 닿을 때·넘을 때의 모양은
 * `DESIGN.md` Inputs / Fields 절의 Character count 가 정한다. 잘렸다는 알림 자리는 늘 있어야 스크린리더가 바뀐 글을
 * 읽으므로 비워 둔 채 둔다.
 */
export function CharacterCount({ id, count, max, isTruncated = false, help }: CharacterCountProps) {
  return (
    <p id={id} className="flex justify-between gap-2 text-xs text-muted-foreground">
      <span className="break-keep">
        {help !== undefined && <span hidden={isTruncated}>{help}</span>}
        <span role="status" className="text-foreground">
          {isTruncated ? `${max}자까지 들어가요. 넘친 글자는 넣지 않았어요.` : ""}
        </span>
      </span>
      <span
        className={cn(
          "shrink-0 tabular-nums",
          count >= max && "font-medium text-foreground",
          count > max && "text-destructive-text",
        )}
      >
        <span className="sr-only">글자 수 </span>
        {count}/{max}
      </span>
    </p>
  );
}
