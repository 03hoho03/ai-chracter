import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import type { RefCallback } from "react";

import type { AttendanceCell } from "@/entities/clover";
import { IdentityRequiredNotice } from "@/entities/identity";

import { formatClaimAreaLines, formatClaimButtonLabel } from "../model/attendanceCopy";
import type { ClaimArea } from "../model/attendanceView";
import type { ClaimFocusTarget } from "../model/claimFocus";

const CLAIM_BUTTON_CLASS = "h-11 w-full sm:w-auto";
const FADE_IN_CLASS = "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200";

type AttendanceClaimAreaProps = {
  area: ClaimArea;
  /** 판의 오늘 칸. 실패·잠시 멈춤 뒤 같은 자리에 수령 버튼을 다시 그릴 때 쓴다. */
  todayCell: AttendanceCell | undefined;
  onClaim: () => void;
  /** 최근 대화방. 받은 뒤 "대화 이어가기" 가 돌아갈 곳이고, 없으면 둘러보기만 둔다. */
  recentRoomId: string | undefined;
  /** 방금 받았는가. 결과 문장이 짧게 나타나는 것은 그때뿐이다 — 다시 들어온 화면에서는 그냥 보인다. */
  isJustClaimed: boolean;
  /** 포커스를 받을 자리. 수령 결과로 포커스가 있던 자리가 사라지면 호출부가 이 ref 로 새 자리에 포커스를 옮긴다. */
  focusRef: (target: ClaimFocusTarget) => RefCallback<HTMLElement>;
};

type ClaimButtonState = { seq: number; amount: number; isClaiming: boolean };

/** 수령 버튼을 그릴 갈래. 실패·잠시 멈춤도 같은 버튼을 다시 누르게 한다. */
function toClaimButton(area: ClaimArea, todayCell: AttendanceCell | undefined): ClaimButtonState | null {
  if (area.kind === "claim") return { seq: area.seq, amount: area.amount, isClaiming: area.isClaiming };
  if ((area.kind === "failed" || area.kind === "paused") && todayCell !== undefined) {
    return { seq: todayCell.seq, amount: todayCell.amount, isClaiming: false };
  }
  return null;
}

/** 판 아래 버튼 자리. 상태가 바뀌어도 같은 자리에서 갈아 끼우고, 최소 높이를 두어 판 아래가 크게 출렁이지 않게 한다.
 * 이 화면의 primary 솔리드 채움은 수령 버튼 하나다.
 *
 * 수령 버튼은 받는 중·실패·잠시 멈춤 갈래를 오가도 트리 속 같은 자리(알림 문장 다음 칸)에 그려 같은 노드로 남는다 — 갈래마다
 * 다른 모양으로 감싸면 버튼이 새로 만들어져 누르던 포커스가 `<body>` 로 떨어진다. 받는 중에도 `disabled` 를 쓰지 않는 것도
 * 같은 이유다(브라우저가 그 순간 포커스를 뺀다). `aria-disabled` 로 알리고 누름은 핸들러에서 막으며, 흐림은 `aria-disabled` 로
 * 막는 이 앱의 다른 버튼들(탈퇴 확인 버튼 등)과 같은 `opacity-65` 를 준다. */
export function AttendanceClaimArea(props: AttendanceClaimAreaProps) {
  const { area, todayCell, onClaim, focusRef } = props;
  const button = toClaimButton(area, todayCell);
  return (
    <div className="flex min-h-11 flex-col items-start gap-3">
      {(area.kind === "failed" || area.kind === "paused") && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {formatClaimAreaLines(area)[0]}
        </p>
      )}
      {button !== null && (
        <Button
          ref={focusRef("button")}
          type="button"
          size="lg"
          aria-disabled={button.isClaiming || undefined}
          className={cn(CLAIM_BUTTON_CLASS, "aria-disabled:pointer-events-none aria-disabled:opacity-65")}
          onClick={() => {
            if (button.isClaiming) return;
            onClaim();
          }}
        >
          {button.isClaiming && <Loader2 aria-hidden className="animate-spin" />}
          {formatClaimButtonLabel(button.seq, button.amount)}
        </Button>
      )}
      <ClaimAreaMessage {...props} />
    </div>
  );
}

/** 버튼 자리를 대신하는 결과·안내 문장. 포커스를 받을 수 있게 `tabIndex={-1}` 을 둔다(Tab 순서에는 넣지 않는다). */
function ClaimAreaMessage({ area, recentRoomId, isJustClaimed, focusRef }: AttendanceClaimAreaProps) {
  switch (area.kind) {
    case "claim":
    case "failed":
    case "paused":
      return null;
    case "checking":
      return (
        <p ref={focusRef("message")} tabIndex={-1} role="status" className="flex items-center gap-2 text-sm text-foreground outline-none">
          <Loader2 aria-hidden className="size-4 shrink-0 animate-spin text-muted-foreground" />
          {formatClaimAreaLines(area)[0]}
        </p>
      );
    case "identity":
      return (
        <div ref={focusRef("message")} tabIndex={-1} className="w-full outline-none">
          <IdentityRequiredNotice reason="attendance" />
        </div>
      );
    case "completed":
    case "claimed": {
      const [headline, detail] = formatClaimAreaLines(area);
      return (
        <>
          <div
            ref={focusRef("message")}
            tabIndex={-1}
            role="status"
            className={cn("flex flex-col gap-1 outline-none", isJustClaimed && FADE_IN_CLASS)}
          >
            <p className="text-sm font-semibold break-keep text-foreground">{headline}</p>
            {detail !== undefined && <p className="text-xs break-keep text-muted-foreground">{detail}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {recentRoomId !== undefined && (
              <Button asChild variant="outline">
                <Link to="/chat/$roomId" params={{ roomId: recentRoomId }}>
                  대화 이어가기
                </Link>
              </Button>
            )}
            <Button asChild variant={recentRoomId !== undefined ? "ghost" : "outline"}>
              <Link to="/">캐릭터 둘러보기</Link>
            </Button>
          </div>
        </>
      );
    }
    case "unavailable":
      return (
        <p ref={focusRef("message")} tabIndex={-1} className="text-sm break-keep text-muted-foreground outline-none">
          {formatClaimAreaLines(area)[0]}
        </p>
      );
  }
}
