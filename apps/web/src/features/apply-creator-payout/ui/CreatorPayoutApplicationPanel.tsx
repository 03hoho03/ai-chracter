import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Link } from "@tanstack/react-router";
import { Check, Circle, CircleDashed, type LucideIcon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import type { CreatorPayoutResponse } from "@/entities/creator-payout";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";
import { formatDate } from "@/shared/lib/time/formatDate";

import { useApplyCreatorPayoutMutation } from "../api/useApplyCreatorPayoutMutation";
import {
  getApplicationView,
  type ApplicationView,
  type Requirement,
  type RequirementKey,
  type RequirementState,
} from "../model/applicationView";
import { APPLY_MESSAGES, toApplyFailure, type ApplyResult } from "../model/applyResult";

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";
const STATUS_BLOCK_CLASS = "flex flex-col gap-1 rounded-xl border border-border px-4 py-3";

type CreatorPayoutApplicationPanelProps = {
  payout: Pick<CreatorPayoutResponse, "application" | "eligibility">;
};

/** 정산 신청 영역. 상태(검토 중·승인·신청 가능)는 `getApplicationView`가 정하고, 여기서는 그 모양대로 그린다.
 *
 * 신청은 모달 없이 이 자리에서 받는다 — 받을 것이 동의 하나뿐이라 화면을 덮을 이유가 없다. "정산 신청하기"가 이 화면의
 * 유일한 솔리드 채움이다(내역의 "더 보기"는 outline). */
export function CreatorPayoutApplicationPanel({ payout }: CreatorPayoutApplicationPanelProps) {
  const view = getApplicationView(payout);

  switch (view.kind) {
    case "pending":
      return (
        <div role="status" className={STATUS_BLOCK_CLASS}>
          <p className="text-sm font-medium text-foreground">신청을 검토하고 있어요</p>
          <p className="text-xs break-keep text-muted-foreground">
            {formatDate(view.appliedAt)}에 신청했어요. 검토 결과는 이 화면에서 확인할 수 있어요.
          </p>
        </div>
      );
    case "approved":
      return (
        <div className={STATUS_BLOCK_CLASS}>
          <p className="text-sm font-medium text-foreground">정산 승인을 받았어요</p>
          <p className="text-xs break-keep text-muted-foreground">
            {view.decidedAt && `${formatDate(view.decidedAt)}에 승인됐어요. `}승인된 동안 적립이 쌓이고, 매달 3일에 지난달
            적립이 확정돼요.
          </p>
        </div>
      );
    case "open":
      return <OpenApplication view={view} />;
  }
}

function OpenApplication({ view }: { view: Extract<ApplicationView, { kind: "open" }> }) {
  return (
    <div className="flex flex-col gap-4">
      {view.previous && <PreviousApplication previous={view.previous} />}
      {view.suspended && (
        <p className="text-sm break-keep text-muted-foreground">이용정지 중에는 정산을 신청할 수 없어요.</p>
      )}
      {!view.suspended && !view.canApply && <RequirementList requirements={view.requirements} />}
      {view.canApply && <ApplyForm />}
    </div>
  );
}

function PreviousApplication({
  previous,
}: {
  previous: NonNullable<Extract<ApplicationView, { kind: "open" }>["previous"]>;
}) {
  const decidedOn = previous.decidedAt ? `${formatDate(previous.decidedAt)} · ` : "";
  return (
    <div className={STATUS_BLOCK_CLASS}>
      <p className="text-sm font-medium text-foreground">
        {previous.status === "rejected" ? "지난 신청이 반려됐어요" : "정산 승인이 취소됐어요"}
      </p>
      {previous.reason && (
        <p className="text-sm break-keep whitespace-pre-line text-foreground">
          <span className="text-muted-foreground">{decidedOn}사유: </span>
          {previous.reason}
        </p>
      )}
      <p className="text-xs break-keep text-muted-foreground">
        {previous.status === "revoked"
          ? "취소 전까지 확정된 적립금은 그대로 남아요. 다시 신청할 수 있어요."
          : "사유를 확인한 뒤 다시 신청할 수 있어요."}
      </p>
    </div>
  );
}

const REQUIREMENT_LABELS: Record<RequirementKey, string> = {
  identity: "휴대폰 본인인증",
  adult: "만 19세 이상",
  publishedWork: "발행한 작품 1개 이상",
};

const REQUIREMENT_ICONS: Record<RequirementState, LucideIcon> = {
  met: Check,
  unmet: Circle,
  unknown: CircleDashed,
};

/** 신청에 모자란 조건. 색으로 가르지 않고 글리프와 오른쪽 글자로 상태를 말한다(무채색 규칙). 고칠 곳이 있는 조건만
 * 그 자리로 가는 링크를 단다 — 인증은 마이페이지, 작품은 빌더. 링크는 문장 밖에 홀로 서 있어 터치 크기를 갖춘 outline
 * 버튼 모양이다(본인인증 안내 `IdentityRequiredNotice` 와 같다). 솔리드는 신청 버튼 몫이다. */
function RequirementList({ requirements }: { requirements: Requirement[] }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm break-keep text-muted-foreground">아래 조건을 갖추면 신청할 수 있어요.</p>
      <ul className="flex flex-col gap-2">
        {requirements.map((requirement) => {
          const Icon = REQUIREMENT_ICONS[requirement.state];
          return (
            <li
              key={requirement.key}
              className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3"
            >
              <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                <Icon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                {REQUIREMENT_LABELS[requirement.key]}
              </span>
              <RequirementStatus requirement={requirement} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RequirementStatus({ requirement }: { requirement: Requirement }) {
  if (requirement.state === "met") return <span className="shrink-0 text-xs text-muted-foreground">갖췄어요</span>;
  if (requirement.state === "unknown") {
    return <span className="shrink-0 text-xs text-muted-foreground">인증 후 확인해요</span>;
  }
  switch (requirement.key) {
    case "identity":
      return (
        <Button asChild variant="outline" size="sm" className="shrink-0">
          <Link to="/mypage">인증하러 가기</Link>
        </Button>
      );
    case "publishedWork":
      return (
        <Button asChild variant="outline" size="sm" className="shrink-0">
          <Link to="/builder">작품 만들기</Link>
        </Button>
      );
    case "adult":
      return <span className="shrink-0 text-xs text-muted-foreground">신청할 수 없어요</span>;
  }
}

/** 수집·이용 동의 하나와 신청 버튼. 동의는 이 신청에만 걸리는 개별 동의라 체크박스를 미리 켜 두지 않는다.
 *
 * 신청 중에는 `disabled` 대신 `aria-disabled` 로 막는다 — `disabled` 는 누른 버튼의 포커스를 날린다. */
function ApplyForm() {
  const fieldId = useId();
  const [agreed, setAgreed] = useState(false);
  const [showsAgreeError, setShowsAgreeError] = useState(false);
  const [result, setResult] = useState<Exclude<ApplyResult, "applied" | "reconsentRequired"> | null>(null);
  const mutation = useApplyCreatorPayoutMutation();
  const agreeErrorId = `${fieldId}-agree-error`;

  const handleApply = async () => {
    if (mutation.isPending) return;
    if (!agreed) {
      setShowsAgreeError(true);
      return;
    }
    setResult(null);
    try {
      await mutation.mutateAsync();
      // 성공하면 신청 상태를 다시 읽어 이 폼이 "검토 중"으로 바뀐다 — 폼 안에 남길 문장이 없어 토스트로 알린다.
      toast.success(APPLY_MESSAGES.applied);
    } catch (error) {
      const failure = toApplyFailure(error);
      // 재동의 모달이 대신 말한다(전역 뮤테이션 처리가 세션을 다시 읽어 띄운다).
      if (failure !== "reconsentRequired") setResult(failure);
    }
  };

  return (
    <div className="flex flex-col items-start gap-4">
      <div className="flex flex-col gap-1.5">
        <label className="flex items-start gap-2 text-sm break-keep text-foreground">
          <Checkbox
            className="mt-0.5"
            checked={agreed}
            onCheckedChange={(checked) => {
              setAgreed(checked === true);
              if (checked === true) setShowsAgreeError(false);
            }}
            aria-invalid={showsAgreeError}
            aria-describedby={showsAgreeError ? agreeErrorId : undefined}
          />
          <span>
            크리에이터 정산 심사와 적립금 정산에 필요한 개인정보를 수집·이용하는 데 동의해요.{" "}
            <span className="text-muted-foreground">(필수)</span>
          </span>
        </label>
        {showsAgreeError && (
          <p id={agreeErrorId} role="alert" className="pl-6 text-xs text-destructive-text">
            동의해야 신청할 수 있어요.
          </p>
        )}
        <p className="pl-6 text-xs break-keep text-muted-foreground">
          자세한 내용은{" "}
          <Link to={SUPPORT_DESTINATIONS.privacy.to} target="_blank" rel="noopener" className={INLINE_LINK_CLASS}>
            {SUPPORT_DESTINATIONS.privacy.label}
          </Link>
          과{" "}
          <Link
            to={SUPPORT_DESTINATIONS["creator-payout-policy"].to}
            target="_blank"
            rel="noopener"
            className={INLINE_LINK_CLASS}
          >
            {SUPPORT_DESTINATIONS["creator-payout-policy"].label}
          </Link>
          에서 볼 수 있어요.
        </p>
      </div>
      <Button aria-disabled={mutation.isPending} className="aria-disabled:opacity-65" onClick={() => void handleApply()}>
        {mutation.isPending ? "신청하는 중…" : "정산 신청하기"}
      </Button>
      {/* 남는 결과는 전부 신청이 되지 않은 경우라 동의 누락과 같은 오류 잉크다(틴트 위가 아닌 글자 전용 토큰). */}
      {result && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {APPLY_MESSAGES[result]}
        </p>
      )}
    </div>
  );
}
