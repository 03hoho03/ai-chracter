import { Button } from "@ai-character-chat/ui/components/button";

import { UserActionConfirmModal } from "./UserActionConfirmModal";

type UserActionPanelProps = {
  userId: string;
  isSuspended: boolean;
  isRateLimitExempt: boolean;
  restrictableContentCount: number;
};

/** ContentActionPanel과 같은 결 — 정지 여부 하나로 분기한다: 정상이면 [경고][정지],
 * 정지 중이면 [경고][정지 해제]. 경고는 정지 중에도 BE가 허용한다.
 * 레이트리밋 면제(limit-goal-prompt.md RL-9)는 정지와 무관한 별개 축이라 정지 여부와 상관없이
 * 항상 한 자리를 차지하고, 현재 면제 여부로만 라벨이 갈린다(RL-22). */
export function UserActionPanel({
  userId,
  isSuspended,
  isRateLimitExempt,
  restrictableContentCount,
}: UserActionPanelProps) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">조치</h2>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void UserActionConfirmModal.call({ userId, action: "warn", restrictableContentCount })}
        >
          경고
        </Button>
        {isSuspended ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void UserActionConfirmModal.call({ userId, action: "unsuspend", restrictableContentCount })
            }
          >
            정지 해제
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void UserActionConfirmModal.call({ userId, action: "suspend", restrictableContentCount })
            }
          >
            정지
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void UserActionConfirmModal.call({
              userId,
              action: isRateLimitExempt ? "rate-limit-exempt-off" : "rate-limit-exempt-on",
              restrictableContentCount,
            })
          }
        >
          {isRateLimitExempt ? "면제 해제" : "레이트리밋 면제"}
        </Button>
        {/* clover-goal-prompt.md CL-16 — 지급·회수는 둘 다 있어야 오지급을 되돌릴 수 있다.
         * 면제 토글과 달리 **상태로 갈리지 않는다** — 잔액이 있든 없든 지급은 늘 가능하고,
         * 회수 가능 여부는 금액에 달려 있어 BE만 판정할 수 있다(422). 그래서 두 버튼을 함께 둔다. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void UserActionConfirmModal.call({ userId, action: "clover-grant", restrictableContentCount })}
        >
          클로버 지급
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void UserActionConfirmModal.call({ userId, action: "clover-revoke", restrictableContentCount })
          }
        >
          클로버 회수
        </Button>
      </div>
    </section>
  );
}
