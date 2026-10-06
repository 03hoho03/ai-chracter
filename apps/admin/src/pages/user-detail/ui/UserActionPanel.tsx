import { Button } from "@ai-character-chat/ui/components/button";
import { useId, type ReactNode } from "react";

import { UserActionConfirmModal } from "./UserActionConfirmModal";

type UserActionPanelProps = {
  userId: string;
  isSuspended: boolean;
  isRateLimitExempt: boolean;
  isBeta: boolean;
  isNovelizeGranted: boolean;
  isChatPremiumModelsGranted: boolean;
  isNovelizePremiumModelsGranted: boolean;
  restrictableContentCount: number;
  restorableContentCount: number;
  /** 조치가 반영되면(확인 모달이 닫힌 뒤) 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** ContentActionPanel과 같은 결 — 정지 여부 하나로 분기한다: 정상이면 [경고][정지],
 * 정지 중이면 [경고][정지 해제]. 경고는 정지 중에도 BE가 허용한다.
 * 레이트리밋 면제는 정지와 무관한 별개 축이라 정지 여부와 상관없이
 * 항상 한 자리를 차지하고, 현재 면제 여부로만 라벨이 갈린다. 베타 지정·소설화 허용·상위 모델 허용(채팅·소설화)도 같은 모양의 별개 축이다.
 *
 * 유저에게 불이익을 주는 징계와 계정 설정(면제·베타·소설화·상위 모델·클로버)을 두 묶음으로 가르고 징계를 위에 둔다 — 한 줄에 섞여
 * 있으면 클로버를 주려다 정지를 누르기 쉽다. 제목·표면은 조치 열·시트가 진다. */
export function UserActionPanel({
  userId,
  isSuspended,
  isRateLimitExempt,
  isBeta,
  isNovelizeGranted,
  isChatPremiumModelsGranted,
  isNovelizePremiumModelsGranted,
  restrictableContentCount,
  restorableContentCount,
  onSuccess,
}: UserActionPanelProps) {
  // 정지·해제 확인창이 예고하는 작품 수. 모달 props 가 조치와 무관하게 같은 모양이라 모든 호출에 함께 넘긴다.
  const commonProps = { userId, restrictableContentCount, restorableContentCount, onSuccess };
  return (
    <div className="flex flex-col gap-4">
      <ActionGroup title="징계">
        <Button
          type="button"
          variant="outline"
          onClick={() => void UserActionConfirmModal.call({ action: "warn", ...commonProps })}
        >
          경고
        </Button>
        {isSuspended ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => void UserActionConfirmModal.call({ action: "unsuspend", ...commonProps })}
          >
            정지 해제
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            onClick={() => void UserActionConfirmModal.call({ action: "suspend", ...commonProps })}
          >
            정지
          </Button>
        )}
      </ActionGroup>

      <ActionGroup title="계정 설정" className="border-t border-border pt-4">
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void UserActionConfirmModal.call({
              action: isRateLimitExempt ? "rate-limit-exempt-off" : "rate-limit-exempt-on",
              ...commonProps,
            })
          }
        >
          {isRateLimitExempt ? "면제 해제" : "레이트리밋 면제"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => void UserActionConfirmModal.call({ action: isBeta ? "beta-off" : "beta-on", ...commonProps })}
        >
          {isBeta ? "베타 해제" : "베타 지정"}
        </Button>
        {/* 허용 행의 유무만 본다 — 전역 스위치·서버 명단 때문에 허용돼 있어도 실제로는 막혀 있을 수 있다. */}
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void UserActionConfirmModal.call({
              action: isNovelizeGranted ? "novelize-off" : "novelize-on",
              ...commonProps,
            })
          }
        >
          {isNovelizeGranted ? "소설화 회수" : "소설화 허용"}
        </Button>
        {/* 상위 모델 허용은 채팅과 소설화가 따로다(스위치·명단도 따로). 소설화 쪽은 소설화 허용도 있어야 쓰이지만 순서는 강제하지
         * 않는다 — 서버도 보지 않으므로 여기서 버튼을 숨기거나 막지 않는다. */}
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void UserActionConfirmModal.call({
              action: isChatPremiumModelsGranted ? "chat-premium-models-off" : "chat-premium-models-on",
              ...commonProps,
            })
          }
        >
          {isChatPremiumModelsGranted ? "채팅 상위 모델 회수" : "채팅 상위 모델 허용"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void UserActionConfirmModal.call({
              action: isNovelizePremiumModelsGranted ? "novelize-premium-models-off" : "novelize-premium-models-on",
              ...commonProps,
            })
          }
        >
          {isNovelizePremiumModelsGranted ? "소설화 상위 모델 회수" : "소설화 상위 모델 허용"}
        </Button>
        {/* 지급·회수는 둘 다 있어야 오지급을 되돌릴 수 있다.
         * 면제 토글과 달리 **상태로 갈리지 않는다** — 잔액이 있든 없든 지급은 늘 가능하고,
         * 회수 가능 여부는 금액에 달려 있어 BE만 판정할 수 있다(422). 그래서 두 버튼을 한 줄에 함께 둔다. */}
        <div className="grid grid-cols-2 gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => void UserActionConfirmModal.call({ action: "clover-grant", ...commonProps })}
          >
            클로버 지급
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void UserActionConfirmModal.call({ action: "clover-revoke", ...commonProps })}
          >
            클로버 회수
          </Button>
        </div>
      </ActionGroup>
    </div>
  );
}

function ActionGroup({ title, className, children }: { title: string; className?: string; children: ReactNode }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={className}>
      <h3 id={headingId} className="mb-2 text-sm font-semibold text-foreground">
        {title}
      </h3>
      <div className="flex flex-col gap-2">{children}</div>
    </section>
  );
}
