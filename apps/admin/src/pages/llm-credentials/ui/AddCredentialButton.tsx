import { Button } from "@ai-character-chat/ui/components/button";

import { STORE_NOTICE_ID } from "./elementIds";

type AddCredentialButtonProps = {
  /** 화면 머리는 이 화면의 유일한 솔리드 채움(`default`), 빈 상태는 윤곽 — 같은 화면에 솔리드가 둘이 되지 않게. */
  variant: "default" | "outline";
  /** 저장소 설정이 없으면 키를 저장할 수 없다. */
  isBlocked: boolean;
  onAdd: () => void;
};

/**
 * 막힌 기본(`primary`) 버튼을 무채색으로 둔다. 기본 비활성처럼 핑크 채움을 반투명으로만 두면 연분홍 덩어리가 남아 눌러야 할 버튼으로
 * 읽힌다. `disabled` 가 아니라 `aria-disabled` 꼴인 것은 포커스·클릭을 받아 막힌 이유(설명)를 키보드로도 읽게 하려는 것이다 — 처리기가
 * 무시한다. 비활성 컨트롤은 대비 요건 밖이다.
 */
const BLOCKED_PRIMARY_CLASS =
  "aria-disabled:bg-secondary aria-disabled:text-muted-foreground aria-disabled:opacity-100";

export function AddCredentialButton({ variant, isBlocked, onAdd }: AddCredentialButtonProps) {
  return (
    <Button
      type="button"
      variant={variant}
      size={variant === "default" ? "default" : "sm"}
      aria-disabled={isBlocked}
      aria-describedby={isBlocked ? STORE_NOTICE_ID : undefined}
      className={variant === "default" ? BLOCKED_PRIMARY_CLASS : "aria-disabled:opacity-65"}
      onClick={() => {
        if (!isBlocked) onAdd();
      }}
    >
      자격 추가
    </Button>
  );
}
