import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  CLOVER_MISSION_LABELS,
  CloverBalance,
  CloverProductLine,
  formatCloverExpiringSoonMessage,
  projectCloverMissionState,
  useClaimCloverMissionMutation,
  useCloverBalanceQuery,
  useCloverMissionsQuery,
  useCloverPricingQuery,
  type CloverMissionItem,
} from "@/entities/clover";
import { IdentityRequiredNotice, isIdentityVerificationRequiredError } from "@/entities/identity";
import { useSessionQuery } from "@/entities/session";
import { PurchaseConfirmDialog, usePaymentRedirect } from "@/features/purchase-clover";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import type { CloverHubSearch } from "../model/cloverHubSearch";
import { getPurchaseSection } from "../model/purchaseSection";
import { findRequestedProduct } from "../model/requestedProduct";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";
const IDENTITY_REQUIRED_MESSAGE = "본인인증을 하면 받을 수 있어요.";
const AGE_RESTRICTED_MESSAGE = "클로버는 만 19세 이상만 구매할 수 있어요.";

/** 미션 수령 실패 토스트. 본인인증 403 은 실패가 아니라 "아직 받을 수 없다"라 오류 토스트가 아니고, 세션은 전역
 * 뮤테이션 처리가 다시 읽어 이 화면이 본인인증 안내로 바뀐다. */
function toastClaimError(error: unknown) {
  if (isIdentityVerificationRequiredError(error)) {
    toast(IDENTITY_REQUIRED_MESSAGE);
    return;
  }
  toast.error(GENERIC_ERROR_MESSAGE);
}

/** 이 회원이 본인인증 게이트에 걸려 있는가와 안내에 쓸 하루 무료 대화 수. 판정은 서버가 라우트 게이트와 같은 함수(면제
 * 회원 포함)로 계산한 세션 값이다. 세션이 아직 없으면 걸리지 않은 것으로 본다(라우트가 세션을 보장한다). */
function useIdentityGate(): { isGated: boolean; dailyFreeChatTurns: number | undefined } {
  const { data: me } = useSessionQuery();
  return { isGated: me?.identityGated ?? false, dailyFreeChatTurns: me?.dailyFreeChatTurns };
}

const SECTION_LINK_CLASS =
  "w-fit text-sm font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline";

/** 클로버 허브 페이지.
 *
 * 컨테이너 폭은 `max-w-md`다. `DESIGN.md` Layout containers 절은 폭을 콘텐츠 밀도로 고르고 텍스트
 * 위주의 한 열인 설정 화면에 `max-w-md`를 준다 — 이 화면도 잔액·구매·미션 세 섹션이 텍스트 몇 줄과
 * 짧은 행뿐이라 그리드도 표도 없는 같은 밀도다. 미션 행은 라벨과 버튼·배지를 양 끝으로 벌리므로
 * (`justify-between`) 컬럼을 넓혀도 그 사이 빈자리만 늘어난다. 이 화면에서만 들어가는 내역 화면도
 * 같은 `max-w-md`라 둘 사이를 오갈 때 컬럼 폭이 바뀌지 않는다.
 *
 * 결제창이 페이지를 떠났다가(모바일) 돌아오는 곳도 여기다 — 라우트가 넘긴 결과 쿼리로 확정을 이어받고 쿼리를 지운다.
 * 상품 안내 화면에서 상품을 고르고 오면(`product`) 그 상품의 구매 확인을 바로 열고 그 파라미터만 지운다.
 */
export function CloverHubPage({
  search,
  onSearchClear,
  onProductClear,
}: {
  search: CloverHubSearch;
  onSearchClear: () => void;
  onProductClear: () => void;
}) {
  usePaymentRedirect(search, onSearchClear);

  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">클로버</h1>
        {/* "클로버 페이지·내역 화면에도 상시 고지를 둔다."
            문구는 entities/clover의 단일 소스(cloverExpiryNotice.ts)를 쓴다 — 내역 화면과
            리터럴을 각자 복사해 갖고 있다가 "7일"과 게시된 공지("7~8일")가 어긋났던 전례가
            있다. */}
        <p className="text-sm break-keep text-muted-foreground">{CLOVER_EXPIRY_NOTICE_MESSAGE}</p>
      </div>

      <BalanceSection />
      <PurchaseSection requestedProductKey={search.product} onRequestedProductHandled={onProductClear} />
      <MissionSection />
    </main>
  );
}

function SectionHeading({ children }: { children: string }) {
  return <h2 className="text-xl font-semibold tracking-tight text-foreground">{children}</h2>;
}

function BalanceSection() {
  const { data, isPending } = useCloverBalanceQuery();
  // 3일 임박 게이트는 BE가 이미 걸었다. FE는 그 값을
  // D-day 문구로만 바꾼다(재판정하지 않는다).
  const expiringMessage = data ? formatCloverExpiringSoonMessage(data.expiringSoon, new Date()) : null;

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>현재 잔액</SectionHeading>
      <div className="flex flex-col gap-1.5">
        {isPending ? (
          <span className="text-sm text-muted-foreground">불러오는 중…</span>
        ) : (
          <CloverBalance balance={data?.balance ?? 0} className="text-sm" />
        )}
        {/* 평소 무채색, 만료 임박일 때만 primary 잉크(솔리드
            채움이 아니다 — 밝기 예산은 화면당 솔리드 채움 하나만 관리한다, `CloverBalance`의
            같은 처방). */}
        {expiringMessage && <p className="text-sm text-primary">{expiringMessage}</p>}
      </div>
      {/* 내역 화면과 상품 안내 진입점. `pages/mypage/ui/MyPagePage.tsx`의 "내 작품" 링크와 같은
          관용구(`font-medium ... text-primary hover:underline focus-visible:underline`). 상품 안내의
          라벨·경로는 목적지 목록에서 가져온다 — 도착 페이지 h1·푸터·이 링크가 한 문자열을 써야 한쪽만 고쳐져
          같은 페이지가 자리마다 다른 이름으로 불리는 일이 없다. */}
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        <Link to="/clover/history" className={SECTION_LINK_CLASS}>
          내역 보기
        </Link>
        <Link to={SUPPORT_DESTINATIONS["clover-pricing"].to} className={SECTION_LINK_CLASS}>
          {SUPPORT_DESTINATIONS["clover-pricing"].label}
        </Link>
      </div>
    </section>
  );
}

/** 클로버 구매. 상품·가격·결제수단·결제 스위치는 전부 `GET /clover/pricing` 응답에서 온다(웹에 가격 사본이 없다).
 *
 * 상품 카드는 outline 이다 — 카드는 고르기만 하고 결제는 다이얼로그에서 하므로, 돈이 나가는 확정의 채움은 구매 확인
 * 다이얼로그 안의 "결제하기" 하나다. 카드 여러 장이 솔리드면 한 화면에 핑크 채움이 상품 수만큼 뜬다. */
type PurchaseBodyProps = {
  /** 상품 안내 화면에서 고르고 온 상품 키(`?product=`). */
  requestedProductKey: string | undefined;
  onRequestedProductHandled: () => void;
};

function PurchaseSection(props: PurchaseBodyProps) {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>클로버 구매</SectionHeading>
      <PurchaseBody {...props} />
    </section>
  );
}

function PurchaseBody({ requestedProductKey, onRequestedProductHandled }: PurchaseBodyProps) {
  const pricingQuery = useCloverPricingQuery();
  const { data: me } = useSessionQuery();
  useOpenRequestedProduct(requestedProductKey, onRequestedProductHandled);

  if (pricingQuery.isPending) {
    return <span className="text-sm text-muted-foreground">불러오는 중…</span>;
  }
  if (pricingQuery.isError) {
    return (
      <p className="text-sm break-keep text-destructive-text">
        클로버 상품을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const { products, payMethods, paymentsEnabled } = pricingQuery.data;
  const section = getPurchaseSection(paymentsEnabled, me);
  if (section === "disabled") {
    return <p className="text-sm break-keep text-muted-foreground">클로버 결제는 아직 준비 중이에요.</p>;
  }
  if (section === "identityRequired" || !me) {
    return <IdentityRequiredNotice reason="purchase" />;
  }
  // 잘못한 것이 없으므로 경고 틴트가 아니라 중립 문장이다. 상품 카드는 눌러도 살 수 없어 두지 않는다.
  if (section === "ageRestricted") {
    return <p className="text-sm break-keep text-muted-foreground">{AGE_RESTRICTED_MESSAGE}</p>;
  }

  return (
    <ul className="flex flex-col gap-3">
      {products.map((product) => (
        <li key={product.key}>
          {/* 카드 자체가 이 섹션의 인터랙션이라 button-outline 레시피를 카드 크기로 쓴다(`bg-background` +
              `hover:bg-muted` + 하우스 포커스 링 + 눌림). */}
          <button
            type="button"
            aria-haspopup="dialog"
            onClick={() => void PurchaseConfirmDialog.call({ product, payMethods, email: me.email })}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-background px-4 py-3 text-left outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px motion-safe:transition-colors"
          >
            <CloverProductLine product={product} />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** 상품 안내 화면에서 고르고 온 상품의 구매 확인을 연다. 가격 응답과 세션이 모두 와서 살 수 있는 상태로 판정된 뒤에만
 * 연다(`findRequestedProduct`). 연 뒤에는 그 파라미터만 지워 새로고침·뒤로가기로 다시 열리지 않게 한다. 같은 키를
 * 두 번 열지 않게 연 키를 ref 로 기억한다 — StrictMode 의 이중 실행에서 창이 두 개 뜬다.
 *
 * effect 는 열 상품이 바뀔 때만 돈다. 콜백과 응답 객체는 렌더마다 새로 만들어지고, 키가 같으면 같은 요청이다. */
function useOpenRequestedProduct(requestedProductKey: string | undefined, onHandled: () => void) {
  const { data: pricing } = useCloverPricingQuery();
  const { data: me } = useSessionQuery();
  const openedKey = useRef<string | null>(null);
  const product = pricing
    ? findRequestedProduct(pricing.products, requestedProductKey, getPurchaseSection(pricing.paymentsEnabled, me))
    : undefined;

  useEffect(() => {
    if (!product || !pricing || !me || openedKey.current === product.key) return;
    openedKey.current = product.key;
    void PurchaseConfirmDialog.call({ product, payMethods: pricing.payMethods, email: me.email });
    onHandled();
  }, [product?.key]);
}

function MissionSection() {
  const { data, isPending } = useCloverMissionsQuery();
  const claimMission = useClaimCloverMissionMutation();
  const { isGated, dailyFreeChatTurns } = useIdentityGate();

  const handleClaim = (key: string) => {
    if (claimMission.isPending) return;
    claimMission.mutate(key, {
      onSuccess: (res) => {
        toast.success(res.granted ? "미션 보상을 받았어요." : "이미 받은 미션이에요.");
      },
      onError: toastClaimError,
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>미션</SectionHeading>
      {/* 안내는 섹션에 한 번만 둔다 — 행마다 두면 같은 문장이 세 번 읽힌다. 행의 "받기"는 아래에서 상태 표시로 바뀐다. */}
      {isGated && <IdentityRequiredNotice reason="free-rewards" dailyFreeChatTurns={dailyFreeChatTurns} />}
      {isPending ? (
        <span className="text-sm text-muted-foreground">불러오는 중…</span>
      ) : (
        <ul className="flex flex-col gap-3">
          {data?.missions.map((mission) => (
            <MissionRow
              key={mission.key}
              mission={mission}
              // 셋 중 지금 청구 중인 것만 로딩 문구를 보여준다 — `variables`는 마지막으로
              // 호출된 인자를 들고 있다(tanstack-query 관례).
              isClaiming={claimMission.isPending && claimMission.variables === mission.key}
              isClaimLocked={isGated}
              onClaim={() => handleClaim(mission.key)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

type MissionRowProps = {
  mission: CloverMissionItem;
  isClaiming: boolean;
  /** 본인인증 전이라 달성한 미션도 받을 수 없다. 누르면 403 이 올 버튼 대신 상태 배지를 둔다. */
  isClaimLocked: boolean;
  onClaim: () => void;
};

function MissionRow({ mission, isClaiming, isClaimLocked, onClaim }: MissionRowProps) {
  const state = projectCloverMissionState(mission);
  const label = CLOVER_MISSION_LABELS[mission.key] ?? mission.key;

  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">클로버 {mission.reward.toLocaleString()}개</span>
      </div>
      {/* DESIGN.md The Brightness Budget Rule — primary 솔리드 채움은 화면당 하나다. 미션은 여러 개가
          동시에 달성될 수 있어 solid면 솔리드 핑크가 한꺼번에 여러 개 뜨므로, 여기는 outline이다. */}
      {state === "claimable" && isClaimLocked && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          본인인증 후 받기
        </span>
      )}
      {state === "claimable" && !isClaimLocked && (
        <Button
          variant="outline"
          size="sm"
          onClick={onClaim}
          aria-disabled={isClaiming}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          {isClaiming ? "받는 중..." : "받기"}
        </Button>
      )}
      {/* DESIGN.md Status badges — 중립 상태는 채움이 아니라 외곽선·텍스트다(`bg-muted`는
          카드·모달 위에서 사라진다). */}
      {state === "claimed" && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          청구완료
        </span>
      )}
      {state === "unachieved" && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          미달성
        </span>
      )}
    </li>
  );
}
