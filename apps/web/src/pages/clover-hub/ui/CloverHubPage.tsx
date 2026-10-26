import { useEffect, useRef, useState } from "react";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  useCloverBalanceQuery,
  useCloverProductsQuery,
  type CloverProductOffer,
  type CloverProductsResponse,
} from "@/entities/clover";
import { useSessionQuery, type MeResponse } from "@/entities/session";
import { PurchaseConfirmDialog, usePaymentRedirect, type SettledPurchase } from "@/features/purchase-clover";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import type { CloverHubSearch } from "../model/cloverHubSearch";
import { toHubViewer } from "../model/hubViewer";
import { getPurchaseSection } from "../model/purchaseSection";
import { resolveRequestedProduct } from "../model/requestedProduct";
import { getWalletView } from "../model/walletView";
import { CloverFaq } from "./CloverFaq";
import { ProductsSection } from "./ProductsSection";
import { PurchaseConditions } from "./PurchaseConditions";
import { WalletSection } from "./WalletSection";

/** 클로버 충전 화면(`/clover`). 로그인 없이 열린다.
 *
 * 한 화면이 두 층이다. 공개 층(구매 조건·충전 상품·클로버 안내)은 누구에게나 같고 상품 응답(`GET /clover/products`)
 * 하나로 그린다. 개인 층(내 클로버·결제 결과)은 로그인했을 때만 잔액(`GET /me/clover`)을 묻는다 — 로그인하지 않은
 * 사람에게 물으면 401 이고, 받지 못한 잔액을 0으로 보이지 않는다. 가격·수량·정책 숫자는 전부 응답에서 온다.
 *
 * 순서는 하나다: 내 클로버 → 구매 조건 → 충전 상품 → 클로버 안내. 좁은 화면은 이 순서의 한 열이고, `lg` 이상에서는
 * 앞의 둘이 왼쪽 열, 뒤의 둘이 오른쪽 열로 나란히 선다. 시각 순서를 CSS `order` 로 바꾸지 않아 탭 순서 = DOM = 시각
 * 순서다. 상태 열이 왼쪽인 이유가 이것이다 — 좁은 화면에서 잔액·결제 결과·구매 조건이 상품보다 먼저 읽혀야 하고(모바일
 * 결제창에서 돌아온 직후 첫 화면에 결과가 보인다), 그 순서를 넓은 화면에서도 `order` 없이 지키려면 DOM 첫 덩어리가
 * 왼쪽이어야 한다. 옆 열을 sticky 로 붙이지 않는다 — 문서 스크롤 화면에서 늘 자리를 차지하는 열은 그 화면만의 레일이고,
 * `DESIGN.md` Navigation 절이 그런 세 번째 크롬 자리를 막는다.
 *
 * 폭은 좁은 화면에서 설정 화면과 같은 `max-w-md` 한 열이고 `lg` 이상에서 `max-w-4xl` 두 열이다. 열 폭의 근거는 이
 * 화면에서 가장 넓은 고대비 잉크인 구매 조건의 자격 문장이다(`DESIGN.md` Layout containers 절 — 가장 넓은 컨트롤이
 * 아니라 가장 넓은 잉크에 맞춘다. 상품 카드는 `w-full` 이라 어느 폭이든 채워 근거가 못 된다). 두 열이 같은 폭(`gap-12`
 * 를 빼고 열마다 400px)이라 `lg` 미만 한 열의 안쪽 폭(400px)과 상품 카드 폭이 같아, 경계를 넘을 때 카드가 늘거나 줄지
 * 않는다. 열을 더 넓혀도 가장 넓은 문장은 따라 늘지 않고 상품 행의 이름·가격 사이만 벌어진다. 두 열은 위에서부터
 * 채우고(`items-start`) 높이를 맞추지 않는다 — 짧은 쪽 아래 빈 바닥은 그리는 상자가 없어 보이지 않는다. 이 화면에서만
 * 들어가는 내역 화면은 목록 한 열이라 `max-w-md` 그대로다.
 *
 * 결제 결과는 토스트가 아니라 내 클로버 맨 위에 그린다 — 구매 확인 창(PC)과 결제창 복귀(모바일)가 같은 자리다. 주소에
 * 담겨 온 상품(`product`)은 살 수 있으면 그 상품의 구매 확인을 바로 열고 그 파라미터만 지운다. */
export function CloverHubPage({
  search,
  onSearchClear,
  onProductClear,
}: {
  search: CloverHubSearch;
  onSearchClear: () => void;
  onProductClear: () => void;
}) {
  const session = useSessionQuery();
  const viewer = toHubViewer(session);
  const productsQuery = useCloverProductsQuery();
  // 잔액은 로그인한 사람에게만 묻는다. 묻지 않는 동안 쿼리는 대기 상태로 남고, 화면 갈래는 `getWalletView` 가 세션으로 먼저
  // 가른다.
  const balanceQuery = useCloverBalanceQuery({ enabled: viewer.kind === "member" });
  const productsHeadingRef = useRef<HTMLHeadingElement>(null);
  const [settled, setSettled] = useState<SettledPurchase | null>(null);

  usePaymentRedirect(search, setSettled, onSearchClear);

  const products = productsQuery.data;
  const section = products ? getPurchaseSection(products.paymentsEnabled, viewer) : undefined;
  const requested =
    products && section ? resolveRequestedProduct(products.products, search.product, section) : { kind: "none" as const };

  const openPurchase = (product: CloverProductOffer, me: MeResponse, pricing: CloverProductsResponse) => {
    void PurchaseConfirmDialog.call({ product, payMethods: pricing.payMethods, email: me.email }).then((result) => {
      if (result) setSettled(result);
    });
  };

  useOpenRequestedProduct(requested.kind === "open" ? requested.product : undefined, (product) => {
    // 연다는 판정(`open`)은 회원이 살 수 있는 상태에서만 나온다 — 이 검사는 그 사실을 타입에 알리는 것뿐이다.
    if (viewer.kind === "member" && products) openPurchase(product, viewer.me, products);
    onProductClear();
  });

  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10 lg:max-w-4xl">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{SUPPORT_DESTINATIONS.clover.label}</h1>
        {/* 문구는 entities/clover의 단일 소스(cloverExpiryNotice.ts)를 쓴다 — 내역 화면과 리터럴을 각자 복사해 갖고
            있다가 "7일"과 게시된 공지("7~8일")가 어긋났던 전례가 있다. */}
        <p className="text-sm break-keep text-muted-foreground">{CLOVER_EXPIRY_NOTICE_MESSAGE}</p>
      </div>

      <div className="grid items-start gap-10 lg:grid-cols-2 lg:gap-12">
        <div className="flex flex-col gap-10">
          <WalletSection
            view={getWalletView(viewer, balanceQuery)}
            settled={settled}
            onRetryBalance={() => void balanceQuery.refetch()}
          />
          <PurchaseConditions section={section} />
        </div>
        <div className="flex flex-col gap-10">
          <ProductsSection
            headingRef={productsHeadingRef}
            products={products?.products}
            isPending={productsQuery.isPending}
            isError={productsQuery.isError}
            onRetry={() => {
              productsHeadingRef.current?.focus();
              void productsQuery.refetch();
            }}
            section={section}
            requested={requested}
            onPick={(product) => {
              if (viewer.kind !== "member" || !products) return;
              // 판매하지 않는 상품 안내는 다른 상품을 고르는 순간 할 일을 다 했다.
              if (search.product !== undefined) onProductClear();
              openPurchase(product, viewer.me, products);
            }}
          />
          <CloverFaq products={products} isError={productsQuery.isError} />
        </div>
      </div>
    </main>
  );
}

/** 주소에 담겨 온 상품의 구매 확인을 연다. 상품 응답과 세션이 모두 와서 살 수 있는 상태로 판정된 뒤에만 열 상품이
 * 온다(`resolveRequestedProduct` 가 `open` 을 줄 때). 같은 키를 두 번 열지 않게 연 키를 ref 로 기억한다 — StrictMode 의
 * 이중 실행에서 창이 두 개 뜬다.
 *
 * effect 는 열 상품이 바뀔 때만 돈다. 콜백과 응답 객체는 렌더마다 새로 만들어지고, 키가 같으면 같은 요청이다. */
function useOpenRequestedProduct(
  product: CloverProductOffer | undefined,
  onOpen: (product: CloverProductOffer) => void,
) {
  const openedKey = useRef<string | null>(null);

  useEffect(() => {
    if (!product || openedKey.current === product.key) return;
    openedKey.current = product.key;
    onOpen(product);
  }, [product?.key]);
}
