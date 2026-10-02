import { Button } from "@ai-character-chat/ui/components/button";

import { UserActionConfirmModal } from "./UserActionConfirmModal";

type UserActionPanelProps = {
  userId: string;
  isSuspended: boolean;
  isRateLimitExempt: boolean;
  isBeta: boolean;
  restrictableContentCount: number;
  restorableContentCount: number;
};

/** ContentActionPanel과 같은 결 — 정지 여부 하나로 분기한다: 정상이면 [경고][정지],
 * 정지 중이면 [경고][정지 해제]. 경고는 정지 중에도 BE가 허용한다.
 * 레이트리밋 면제는 정지와 무관한 별개 축이라 정지 여부와 상관없이
 * 항상 한 자리를 차지하고, 현재 면제 여부로만 라벨이 갈린다. 베타 지정도 같은 모양의 별개 축이다. */
export function UserActionPanel({
  userId,
  isSuspended,
  isRateLimitExempt,
  isBeta,
  restrictableContentCount,
  restorableContentCount,
}: UserActionPanelProps) {
  // 정지·해제 확인창이 예고하는 작품 수. 모달 props 가 조치와 무관하게 같은 모양이라 모든 호출에 함께 넘긴다.
  const previewCounts = { restrictableContentCount, restorableContentCount };
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">조치</h2>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void UserActionConfirmModal.call({ userId, action: "warn", ...previewCounts })}
        >
          경고
        </Button>
        {isSuspended ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void UserActionConfirmModal.call({ userId, action: "unsuspend", ...previewCounts })
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
              void UserActionConfirmModal.call({ userId, action: "suspend", ...previewCounts })
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
              ...previewCounts,
            })
          }
        >
          {isRateLimitExempt ? "면제 해제" : "레이트리밋 면제"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void UserActionConfirmModal.call({
              userId,
              action: isBeta ? "beta-off" : "beta-on",
              ...previewCounts,
            })
          }
        >
          {isBeta ? "베타 해제" : "베타 지정"}
        </Button>
        {/* 지급·회수는 둘 다 있어야 오지급을 되돌릴 수 있다.
         * 면제 토글과 달리 **상태로 갈리지 않는다** — 잔액이 있든 없든 지급은 늘 가능하고,
         * 회수 가능 여부는 금액에 달려 있어 BE만 판정할 수 있다(422). 그래서 두 버튼을 함께 둔다. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void UserActionConfirmModal.call({ userId, action: "clover-grant", ...previewCounts })}
        >
          클로버 지급
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void UserActionConfirmModal.call({ userId, action: "clover-revoke", ...previewCounts })
          }
        >
          클로버 회수
        </Button>
      </div>
    </section>
  );
}
