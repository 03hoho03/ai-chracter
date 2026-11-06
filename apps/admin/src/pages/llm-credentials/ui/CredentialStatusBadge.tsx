import { cn } from "@ai-character-chat/ui/lib/utils";
import { CircleAlert, CircleDashed, CircleDot, CirclePause, type LucideIcon } from "lucide-react";

import { credentialStatusText } from "../model/labels";
import type { CredentialStatus } from "../model/status";
import { NEUTRAL_BADGE_CLASS, PROBLEM_BADGE_CLASS } from "./badgeClasses";

type CredentialStatusBadgeProps = {
  status: CredentialStatus;
};

/** 항목 상태 표지. 뜻은 글자가 지고 아이콘은 `aria-hidden` 이다 — 색만으로 가르지 않는다. 문제 상태(소진·미확인)만 `destructive`
 * 틴트이고, "사용 중"은 무채 윤곽에 잉크만 올린다(운영자가 읽어야 할 상태). */
export function CredentialStatusBadge({ status }: CredentialStatusBadgeProps) {
  const { Icon, className } = badgeLook(status);

  return (
    <span className={className}>
      <Icon aria-hidden className="size-3" />
      {credentialStatusText(status)}
    </span>
  );
}

function badgeLook(status: CredentialStatus): { Icon: LucideIcon; className: string } {
  switch (status.kind) {
    case "serving":
      return { Icon: CircleDot, className: cn(NEUTRAL_BADGE_CLASS, "text-foreground") };
    case "standby":
      return { Icon: CirclePause, className: NEUTRAL_BADGE_CLASS };
    case "unverified":
    case "exhausted":
      return { Icon: CircleAlert, className: PROBLEM_BADGE_CLASS };
    case "disabled":
      return { Icon: CircleDashed, className: NEUTRAL_BADGE_CLASS };
    default:
      return assertNever(status);
  }
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 상태: ${JSON.stringify(value)}`);
}
