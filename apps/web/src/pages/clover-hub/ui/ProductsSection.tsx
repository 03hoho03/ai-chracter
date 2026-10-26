import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouter } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import type { ReactNode, Ref } from "react";

import { CloverProductLine, type CloverProductOffer } from "@/entities/clover";
import { CONTACT_EMAIL } from "@/shared/config/site";

import { getProductsFootnote } from "../model/productsFootnote";
import type { PurchaseSection } from "../model/purchaseSection";
import type { RequestedProduct } from "../model/requestedProduct";
import { HubSection, INLINE_LINK_CLASS } from "./HubSection";

/** 상품 행 껍데기 — button-outline 레시피를 카드 크기로 쓴다(`bg-background` + `hover:bg-muted` + 하우스 포커스 링 +
 * 눌림). `background` 위라 `hover:bg-muted` 가 보인다 — `bg-card` 로 바꾸면 hover 가 사라진다. */
const PRODUCT_CARD_CLASS =
  "flex w-full items-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-left outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px motion-safe:transition-colors";

type ProductsSectionProps = {
  headingRef: Ref<HTMLHeadingElement>;
  products: readonly CloverProductOffer[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  section: PurchaseSection | undefined;
  requested: RequestedProduct<CloverProductOffer>;
  onPick: (product: CloverProductOffer) => void;
  /** 이 화면이 받은 복귀 주소. 로그인하러 갔다 돌아올 주소에도 실어 충전 뒤 돌아갈 곳을 잃지 않는다. */
  returnTo: string | undefined;
};

/** 충전 상품. 행 모양은 누르면 일어나는 일에 따라 셋이다 — 살 수 있으면 구매 확인을 여는 버튼, 로그인하지 않았으면
 * 로그인으로 가는 링크, 지금 살 수 없으면 누를 수 없는 정보 행(할 수 없는 동작을 약속하지 않는다). 세션을 묻는 동안은
 * 어느 모양인지 몰라 행을 그리지 않는다.
 *
 * 상품 카드는 outline 이다 — 카드는 고르기만 하고 결제는 다이얼로그에서 하므로, 돈이 나가는 확정의 채움은 구매 확인
 * 다이얼로그 안의 "결제하기" 하나다. 카드 여러 장이 솔리드면 한 화면에 핑크 채움이 상품 수만큼 뜬다.
 *
 * 제목은 로딩·실패·성공 어느 상태에서나 같은 자리에 남는다 — 실패할 때 제목까지 사라지면 이 화면에 상품이 있다는 사실이
 * 함께 사라진다. 다시 시도를 누르면 실패 패널(과 그 버튼)이 언마운트되므로 누르는 즉시 포커스를 제목으로 옮긴다. */
export function ProductsSection({
  headingRef,
  products,
  isPending,
  isError,
  onRetry,
  section,
  requested,
  onPick,
  returnTo,
}: ProductsSectionProps) {
  return (
    <HubSection title="충전 상품" headingRef={headingRef}>
      <RequestedProductNotice requested={requested} />
      {isPending && <ProductListSkeleton />}
      {isError && !products && <ProductsErrorState onRetry={onRetry} />}
      {products && section && <ProductList products={products} section={section} onPick={onPick} returnTo={returnTo} />}
    </HubSection>
  );
}

function ProductList({
  products,
  section,
  onPick,
  returnTo,
}: {
  products: readonly CloverProductOffer[];
  section: PurchaseSection;
  onPick: (product: CloverProductOffer) => void;
  returnTo: string | undefined;
}) {
  if (section === "pending") return <ProductListSkeleton />;
  if (products.length === 0) {
    return (
      <EmptyPanel>
        <p className="text-sm text-muted-foreground">지금 판매 중인 클로버 상품이 없어요.</p>
      </EmptyPanel>
    );
  }

  switch (section) {
    case "products":
      return (
        <ul className="flex flex-col gap-3">
          {products.map((product) => (
            <li key={product.key}>
              <button type="button" aria-haspopup="dialog" onClick={() => onPick(product)} className={PRODUCT_CARD_CLASS}>
                <CloverProductLine product={product} />
              </button>
            </li>
          ))}
        </ul>
      );
    case "guest":
      return (
        <>
          <ul className="flex flex-col gap-3">
            {products.map((product) => (
              <li key={product.key}>
                <LoginProductLink product={product} returnTo={returnTo} />
              </li>
            ))}
          </ul>
          <ProductsFootnoteLine section={section} />
        </>
      );
    case "disabled":
    case "identityRequired":
    case "ageRestricted":
      return (
        <>
          {/* 누를 수 없는 행은 테두리 상자로 감싸지 않는다 — 누르는 상품 카드와 같은 모양이면 눌러도 반응이 없는
              카드로 읽힌다. 행마다 아래 선 하나로만 가르고 목록 위에 선 하나를 둔다(간격은 `gap-*` 만 쓰는 규칙이라
              `divide-*` 를 쓰지 않는다). */}
          <ul className="flex flex-col border-t border-border">
            {products.map((product) => (
              <li key={product.key} className="flex border-b border-border py-3">
                <CloverProductLine product={product} />
              </li>
            ))}
          </ul>
          <ProductsFootnoteLine section={section} />
        </>
      );
  }
}

/** 상품 목록 아래 한 줄. 무엇을 말할지와 넓은 화면에서만 보일지는 `getProductsFootnote` 가 정한다. */
function ProductsFootnoteLine({ section }: { section: PurchaseSection }) {
  const footnote = getProductsFootnote(section);
  if (!footnote) return null;
  return (
    <p className={cn("text-xs break-keep text-muted-foreground", footnote.isWideOnly && "hidden lg:block")}>
      {footnote.text}
    </p>
  );
}

/** 로그인하지 않은 사람의 상품 행. 이 화면 자신이 아니라 로그인으로 바로 보낸다 — 이 화면은 로그인 없이 열리므로
 * 자신의 `?product=` 주소로 보내면 같은 화면이 다시 그려질 뿐이다. 로그인한 뒤에는 그 상품을 담은 이 화면으로 돌아와
 * 구매 확인이 열린다. 다른 화면으로 넘어가는 행이라 끝에 셰브런을 두고, 보이는 상품 정보 뒤에 목적지를 덧붙인다
 * (`aria-label` 로 덮으면 보이는 글자와 읽는 이름이 갈린다). */
function LoginProductLink({ product, returnTo }: { product: CloverProductOffer; returnTo: string | undefined }) {
  const router = useRouter();
  const redirect = router.buildLocation({ to: "/clover", search: { product: product.key, returnTo } }).href;

  return (
    <Link to="/login" search={{ redirect }} className={PRODUCT_CARD_CLASS}>
      <CloverProductLine product={product} />
      <span className="sr-only">로그인하고 구매하기</span>
      <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

/** 주소에 담겨 온 상품(`?product=`)에 대한 한 줄. 잘못한 것이 없으므로 경고 틴트가 아니라 중립 표면(보더 한 줄)이다.
 * 판매하지 않는 키는 비슷한 상품으로 바꿔 열지 않고 그렇다고만 말한다. 본인인증 안내에서는 구매 확인이 저절로 다시
 * 열린다고 하지 않는다 — 인증은 마이페이지에서 하고, 이 주소로 돌아오는 길에 따라 `?product=` 가 남지 않을 수 있다. */
function RequestedProductNotice({ requested }: { requested: RequestedProduct<CloverProductOffer> }) {
  const message = (() => {
    switch (requested.kind) {
      case "none":
      case "open":
        return null;
      case "chosen":
        return `고른 상품: ${requested.product.name} · ${requested.product.priceKrw.toLocaleString()}원. 로그인하면 결제로 이어져요.`;
      case "afterIdentity":
        return `본인인증을 마치면 고른 상품(${requested.product.name})을 여기서 살 수 있어요.`;
      case "unavailable":
        return "주소에 담긴 상품은 지금 판매하지 않아요. 아래에서 다른 상품을 골라 주세요.";
    }
  })();
  if (!message) return null;

  return (
    <p role="status" className="rounded-lg border border-border px-3.5 py-2.5 text-xs break-keep text-muted-foreground">
      {message}
    </p>
  );
}

/** 보여 줄 내용이 없는 자리의 점선 패널(`DESIGN.md` Components 절 Empty state 레시피, `ContentListEmptyState`와 같은
 * 셸 클래스). */
function EmptyPanel({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center break-keep">
      {children}
    </div>
  );
}

/** 상품 응답을 못 받았을 때. 위험한 동작이 아니라 `destructive` 글자를 쓰지 않는다(곁의 정책 문장 위에 빨간 글자가
 * 뜨면 정책이 틀린 것처럼 읽힌다). 다시 시도는 이 패널의 유일한 앞길이라 기본 크기 버튼이다. */
function ProductsErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <EmptyPanel>
      <div role="alert" className="flex flex-col gap-1.5">
        <p className="text-lg font-semibold text-foreground">상품 정보를 불러오지 못했어요</p>
        <p className="text-sm text-muted-foreground">
          계속 안 되면{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className={INLINE_LINK_CLASS}>
            {CONTACT_EMAIL}
          </a>
          로 알려주세요.
        </p>
      </div>
      <Button type="button" variant="outline" onClick={onRetry}>
        다시 시도
      </Button>
    </EmptyPanel>
  );
}

/** 진행 표시라 `motion-safe:`로 가두지 않는다(멈추면 "멈춘 UI"로 읽힌다 — `DESIGN.md` Motion 절). */
function ProductListSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-3">
      {["first", "second", "third"].map((key) => (
        <div key={key} className="h-16 animate-pulse rounded-xl bg-muted" />
      ))}
    </div>
  );
}
