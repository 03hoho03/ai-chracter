import { Button } from "@ai-character-chat/ui/components/button";
import { Link, useRouterState } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useRef, type FocusEvent } from "react";

import {
  CLOVER_MISSIONS_SECTION_ID,
  CloverWallet,
  formatCloverExpiringSoonMessage,
  formatCloverExpiryNotice,
  type CloverBalanceResponse,
} from "@/entities/clover";
import { loginRedirectTarget } from "@/entities/session";
import { formatPurchaseGrant, PURCHASE_MESSAGES, type SettledPurchase } from "@/features/purchase-clover";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import type { PurchaseSection } from "../model/purchaseSection";
import { returnLinkLabel } from "../model/returnTo";
import { getGuestLoginLabel, type WalletView } from "../model/walletView";
import { HubSection, SECTION_LINK_CLASS } from "./HubSection";

/** 이 화면을 연 사람이 옛 API 응답(잔액을 나눈 몫이 아직 없다)을 받는 구간이 있다 — web 과 API 는 따로 배포된다. 타입은
 * 그 칸을 필수로 적지만 그 구간에는 런타임에 비어 있으므로 비어 있을 수 있는 모양으로 읽는다. */
type DeployedBalanceResponse = Omit<CloverBalanceResponse, "breakdown"> & Partial<Pick<CloverBalanceResponse, "breakdown">>;

type WalletSectionProps = {
  view: WalletView<DeployedBalanceResponse>;
  /** 구매 확인 창이나 결제창 복귀가 끝낸 결과. 새로고침하면 사라진다(복귀 쿼리는 이미 지웠다). */
  settled: SettledPurchase | null;
  /** 상품 행 갈래. 비로그인 로그인 버튼이 충전을 약속해도 되는지 가른다(`getGuestLoginLabel`). */
  section: PurchaseSection | undefined;
  /** "확인 중"으로 끝난 뒤 잔액이 늘었는가(`isCheckingResolved`). 늘었으면 그 안내를 반영됐다는 문장으로 바꾼다. */
  isCheckingResolved: boolean;
  onRetryBalance: () => void;
  /** 충전에 성공하면 결과 블록이 솔리드 버튼으로 보낼 복귀 주소(`getReturnPlacement`). 없으면 버튼을 그리지 않는다. */
  solidReturnTo: string | undefined;
};

/** "내 클로버". 로그인한 사람에게만 잔액을 묻고, 그 밖의 상태에서는 0을 그리지 않는다(`getWalletView`).
 *
 * 결제 결과는 이 섹션 맨 위에 그린다 — 모바일 결제창에서 돌아온 직후 첫 화면에 보이는 자리이고, 다이얼로그 결제(PC)도
 * 같은 자리를 쓴다. 결과 아래의 총잔액이 새 값으로 바뀌는 것을 바로 이어 읽을 수 있다. */
export function WalletSection({
  view,
  settled,
  section,
  isCheckingResolved,
  onRetryBalance,
  solidReturnTo,
}: WalletSectionProps) {
  return (
    <HubSection title="내 클로버">
      {settled && (
        <PurchaseOutcome
          settled={settled}
          isCheckingResolved={isCheckingResolved}
          onRetryBalance={onRetryBalance}
          solidReturnTo={solidReturnTo}
        />
      )}
      <WalletBody view={view} section={section} onRetryBalance={onRetryBalance} />
    </HubSection>
  );
}

function WalletBody({
  view,
  section,
  onRetryBalance,
}: Pick<WalletSectionProps, "view" | "section" | "onRetryBalance">) {
  // 로그인한 뒤 지금 주소로 돌아온다 — 주소에 담긴 상품(`?product=`)도 함께 돌아와 그 상품의 결제로 이어진다.
  const loginRedirect = useRouterState({ select: (state) => loginRedirectTarget(state.location) });

  switch (view.kind) {
    case "pending":
      // 진행 표시라 `motion-safe:` 로 가두지 않는다(멈추면 "멈춘 UI"로 읽힌다 — `DESIGN.md` Motion 절).
      return (
        <div aria-hidden className="flex flex-col gap-3">
          <div className="h-7 w-44 animate-pulse rounded-md bg-muted" />
          <div className="flex flex-col gap-1.5">
            {["paid", "bonus", "free"].map((key) => (
              <div key={key} className="h-5 animate-pulse rounded-md bg-muted" />
            ))}
          </div>
        </div>
      );
    case "guest":
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm break-keep text-muted-foreground">
            로그인하면 남은 클로버와 소멸 예정일을 볼 수 있어요.
          </p>
          {/* 이 화면의 솔리드 채움은 결제 성공 뒤 "대화로 돌아가기" 몫이라 outline 이다. */}
          <Button asChild variant="outline">
            <Link to="/login" search={{ redirect: loginRedirect }}>
              {getGuestLoginLabel(section)}
            </Link>
          </Button>
        </div>
      );
    case "error":
      return (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm break-keep text-muted-foreground">잔액을 불러오지 못했어요.</p>
            <Button type="button" variant="outline" size="sm" onClick={onRetryBalance}>
              다시 시도
            </Button>
          </div>
          <MemberLinks />
        </div>
      );
    case "ready": {
      // 3일 임박 게이트는 BE가 이미 걸었다. FE는 그 값을 D-day 문구로만 바꾼다(재판정하지 않는다).
      const expiringMessage = formatCloverExpiringSoonMessage(view.balance.expiringSoon, new Date());
      return (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <CloverWallet balance={view.balance.balance} breakdown={view.balance.breakdown} />
            {/* 무료로 받은 클로버의 소멸 고지는 무료 몫 바로 아래에 둔다. 화면 첫 줄에 두면 처음 사는 사람이 산 클로버도 일주일이면
                사라진다고 읽는다 — 구매분 유효기간은 클로버 안내가 말한다. 문구는 entities/clover 의 단일 소스
                (cloverExpiryNotice.ts)라 내역 화면과 같다. */}
            <p className="text-xs break-keep text-muted-foreground">{formatCloverExpiryNotice()}</p>
          </div>
          {/* 평소 무채색, 만료 임박일 때만 primary 잉크(솔리드 채움이 아니다 — 밝기 예산은 화면당 솔리드 채움 하나만
              관리한다, `CloverBalance`의 같은 처방). */}
          {expiringMessage && <p className="text-sm text-primary">{expiringMessage}</p>}
          <MemberLinks />
        </div>
      );
    }
  }
}

/** 내역과 미션 진입점. 미션 보상 받기는 마이페이지의 미션 섹션으로 바로 간다 — 이 화면에서 미션을 받던 사람의 길이다. */
function MemberLinks() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      <Link to="/clover/history" className={SECTION_LINK_CLASS}>
        내역 보기
      </Link>
      <Link to="/mypage" hash={CLOVER_MISSIONS_SECTION_ID} className={SECTION_LINK_CLASS}>
        미션 보상 받기
      </Link>
    </div>
  );
}

const CHECKING_RESOLVED_MESSAGE = "결제가 확인돼 잔액에 반영됐어요.";

/** 끝난 결제의 결과. 나타날 때 결과 문장으로 포커스를 옮긴다 — 구매 확인 창이 닫히면 포커스가 누른 상품 행으로
 * 돌아가 결과를 놓친다. 창이 닫히며 포커스를 정리하는 일이 다음 프레임까지 이어지므로 두 프레임 뒤에 옮긴다.
 *
 * 축하 연출·초록 성공색은 없다(아이콘과 문장). 문제 갈래만 `destructive` 틴트이고, 확인 중은 진행 표시라 스피너를 가두지
 * 않는다. 확인 중에는 총잔액을 올려 보이지 않는다 — 결제사가 아직 확정하지 않았을 수 있다. 그 뒤 다시 불러온 잔액이
 * 늘었으면 확인 중 안내를 반영됐다는 문장으로 바꾸고 스피너·다시 불러오기를 거둔다. 블록을 닫지 않고 같은 제목 요소의
 * 글자만 바꾼다 — 포커스가 그 제목에 있어, 요소가 사라지면 포커스가 `<body>` 로 떨어진다.
 *
 * 충전하러 온 화면이 있으면(복귀 주소) 성공 블록에 그리로 돌아가는 솔리드 버튼을 둔다 — 이 화면의 유일한 솔리드 채움이다.
 * 누르면 이동만 한다. 거절됐던 메시지는 채팅 방이 입력창에 되살려 두고, 다시 보낼지는 그 방의 전송 버튼이 정한다. */
function PurchaseOutcome({
  settled,
  isCheckingResolved,
  onRetryBalance,
  solidReturnTo,
}: {
  settled: SettledPurchase;
  isCheckingResolved: boolean;
  onRetryBalance: () => void;
  solidReturnTo: string | undefined;
}) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const isFocusInside = useRef(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      requestAnimationFrame(() => titleRef.current?.focus());
    });
    return () => cancelAnimationFrame(frame);
  }, [settled]);

  // 반영됐다는 문장으로 바뀌면 "잔액 다시 불러오기"가 사라진다. 그 버튼(또는 블록 안 다른 곳)에 포커스가 있었으면 포커스가
  // `<body>` 로 떨어지므로 결과 제목으로 옮긴다. 블록 밖에 있던 포커스는 건드리지 않는다.
  useEffect(() => {
    if (isCheckingResolved && isFocusInside.current) titleRef.current?.focus();
  }, [isCheckingResolved]);

  /** 포커스가 블록 안에 있는지 기억한다. 포커스를 가진 요소가 지워질 때 브라우저가 내는 blur 는 갈 곳(`relatedTarget`)이
   * 없고 그 요소가 이미 문서에서 빠져 있어, 그 경우는 블록을 떠난 것으로 치지 않는다. */
  const focusTracking = {
    onFocus: () => {
      isFocusInside.current = true;
    },
    onBlur: (event: FocusEvent<HTMLDivElement>) => {
      const next = event.relatedTarget;
      if (next instanceof Node ? !event.currentTarget.contains(next) : event.target.isConnected) {
        isFocusInside.current = false;
      }
    },
  };

  const title = (
    <h3 ref={titleRef} tabIndex={-1} className="text-sm font-semibold break-keep text-foreground outline-none">
      {settled.result === "checking" && isCheckingResolved ? CHECKING_RESOLVED_MESSAGE : PURCHASE_MESSAGES[settled.result]}
    </h3>
  );

  switch (settled.result) {
    case "paid":
      return (
        <div role="status" className="flex flex-col items-start gap-3 rounded-xl border border-border px-4 py-3">
          <div className="flex flex-col gap-1">
            {title}
            {settled.grant && (
              <p className="text-sm break-keep text-muted-foreground">{formatPurchaseGrant(settled.grant)}</p>
            )}
          </div>
          {solidReturnTo !== undefined && (
            <Button asChild>
              <Link to={solidReturnTo}>{returnLinkLabel(solidReturnTo)}</Link>
            </Button>
          )}
        </div>
      );
    case "checking":
      return (
        <div
          role="status"
          className="flex flex-col items-start gap-3 rounded-xl border border-border px-4 py-3"
          {...focusTracking}
        >
          <div className="flex items-start gap-2">
            {!isCheckingResolved && (
              <Loader2 aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
            )}
            {title}
          </div>
          {/* 웹훅이 먼저 지급했으면 다시 불러온 잔액에 보인다. */}
          {!isCheckingResolved && (
            <Button type="button" variant="outline" size="sm" onClick={onRetryBalance}>
              잔액 다시 불러오기
            </Button>
          )}
        </div>
      );
    case "notCompleted":
      return (
        <div role="status" className="flex flex-col gap-1 rounded-xl border border-border px-4 py-3">
          {title}
          {/* 다시 결제할 상품 행이 바로 아래(넓은 화면에서는 옆)에 있어 따로 버튼을 두지 않는다. */}
          <p className="text-sm break-keep text-muted-foreground">다시 결제하거나 다른 결제수단을 고를 수 있어요.</p>
        </div>
      );
    case "problem":
      return (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-xl bg-destructive/10 px-4 py-3">
          <h3 ref={titleRef} tabIndex={-1} className="text-sm break-keep text-destructive-text outline-none">
            {PURCHASE_MESSAGES.problem}
          </h3>
          <Link
            to={SUPPORT_DESTINATIONS["inquiry-new"].to}
            className="text-sm font-medium text-destructive-text underline underline-offset-4 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
          >
            {SUPPORT_DESTINATIONS["inquiry-new"].label}
          </Link>
        </div>
      );
  }
}
