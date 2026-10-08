import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  CloverIcon,
  useCloverPricingQuery,
  type CloverProductItem,
} from "@/entities/clover";
import { CONTACT_EMAIL } from "@/shared/config/site";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

const INLINE_LINK_CLASSNAME =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

/** `/clover/pricing` — 로그인 없이 보는 클로버 상품 안내.
 *
 * 가격·수량·단가 숫자는 전부 `GET /clover/pricing` 응답에서 온다. 이 파일에 숫자를 적으면 상품을 바꿀 때
 * 서버와 화면이 갈린다. 반면 유효기간·7일·환불 비율·사용 순서는 정책 문장이라 여기 적고, 같은 문장이
 * 이용약관과 환불정책(둘 다 DB 게시본)에도 있다 — 셋 중 하나를 고치면 나머지와 함께 맞춘다.
 *
 * 컨테이너는 클로버 허브와 같은 `max-w-md` 한 열이다. 텍스트 몇 줄과 짧은 행뿐이라 넓혀도 행 가운데 빈자리만
 * 는다. 결제는 아직 열리지 않아 버튼을 두지 않는다 — 누를 수 없는 결제 버튼은 할 수 없는 동작을 약속한다.
 */
export function CloverPricingPage() {
  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {SUPPORT_DESTINATIONS["clover-pricing"].label}
        </h1>
        <p className="text-sm break-keep text-muted-foreground">
          클로버는 대화와 이미지 생성에 쓰여요. 클로버 결제는 아직 준비 중이에요.
        </p>
      </div>

      <PricingBody />

      <Section title="유효기간과 사용 순서">
        <PolicyList
          items={[
            "유료 클로버와 보너스 클로버는 구매일로부터 5년 동안 쓸 수 있어요.",
            CLOVER_EXPIRY_NOTICE_MESSAGE,
            "클로버는 무료, 보너스, 유료 순서로 쓰여요. 무료 클로버는 환불되지 않아요.",
            "본인인증 기능이 열리면, 출석·미션 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.",
          ]}
        />
      </Section>

      <Section title="청약철회와 환불">
        <PolicyList
          items={[
            "결제일로부터 7일 안에는 쓰지 않은 유료 클로버를 전액 돌려받을 수 있어요. 이미 쓴 보너스 클로버만큼은 빼고 돌려드려요.",
            "7일이 지나면 남은 유료 클로버의 90%를 돌려받을 수 있어요.",
            "이미 쓴 클로버는 청약철회할 수 없어요. 클로버는 쓰는 즉시 기능 이용에 제공되기 때문이에요.",
            "보너스 클로버는 따로 환불되지 않아요. 유료 클로버를 환불하면 그 구매로 받은 보너스 클로버 중 남은 것은 회수돼요.",
            "탈퇴하면 남은 클로버가 모두 사라져요. 남은 유료 클로버는 탈퇴하기 전에 환불을 신청해 주세요.",
            `이용이 정지된 동안에도 ${CONTACT_EMAIL}로 환불을 신청할 수 있어요.`,
          ]}
        />
        <p className="text-sm break-keep text-foreground">
          자세한 기준은{" "}
          <Link to={SUPPORT_DESTINATIONS["refund-policy"].to} className={INLINE_LINK_CLASSNAME}>
            {SUPPORT_DESTINATIONS["refund-policy"].label}
          </Link>
          에서 볼 수 있어요.
        </p>
      </Section>

      <Section title="미성년자 결제">
        <p className="text-sm break-keep text-foreground">
          미성년자가 법정대리인의 동의 없이 결제했다면 본인이나 법정대리인이 취소할 수 있어요. 다만 성년자인 것처럼
          속였거나, 법정대리인이 쓰도록 허락한 용돈의 범위에서 결제했다면 취소할 수 없어요.
        </p>
      </Section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      {children}
    </section>
  );
}

function PolicyList({ items }: { items: readonly string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-2 pl-5 text-sm break-keep text-foreground marker:text-muted-foreground">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/** 상품과 쓰임새는 응답이 있어야 그릴 수 있어 여기서만 로딩·에러를 가른다. 제목과 정책 문장은 응답과 무관해
 * 바깥에 둔다(`pages/legal-document`의 관용구 — 실패해도 환불 조건은 읽힌다). */
function PricingBody() {
  const pricingQuery = useCloverPricingQuery();

  if (pricingQuery.isPending) {
    return <PricingSkeleton />;
  }

  if (pricingQuery.isError) {
    return (
      <p className="text-sm break-keep text-destructive-text">
        클로버 상품을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const { products, chatTurnCost, imageCost } = pricingQuery.data;
  const [exampleProduct] = products;

  return (
    <>
      <Section title="충전 상품">
        <ul className="flex flex-col gap-3">
          {products.map((product) => (
            <ProductRow key={product.key} product={product} />
          ))}
        </ul>
        <p className="text-xs break-keep text-muted-foreground">가격은 부가세 포함이에요.</p>
      </Section>

      <Section title="쓰임새">
        {/* 단가는 기본 모델 기준만 있다 — 상위 모델은 허용된 계정만 쓰고 단가가 달라 공개 안내에 싣지 않는다. */}
        <dl className="flex flex-col gap-3">
          <UsageRow label="대화 1턴" cost={chatTurnCost} />
          <UsageRow label="이미지 1장" cost={imageCost} />
        </dl>
        <p className="text-xs break-keep text-muted-foreground">기본 AI 모델 기준이에요.</p>
        {exampleProduct && (
          <p className="text-sm break-keep text-foreground">
            예를 들어 클로버 {totalAmount(exampleProduct).toLocaleString()}개로 대화를{" "}
            {Math.floor(totalAmount(exampleProduct) / chatTurnCost).toLocaleString()}턴 하거나 이미지를{" "}
            {Math.floor(totalAmount(exampleProduct) / imageCost).toLocaleString()}장 만들 수 있어요.{" "}
            <span className="text-muted-foreground">이해를 돕기 위한 예시예요.</span>
          </p>
        )}
        <p className="text-sm break-keep text-foreground">
          결제하기 전에 무료 클로버로 대화와 이미지 생성을 먼저 써 볼 수 있어요.
        </p>
      </Section>
    </>
  );
}

function totalAmount(product: CloverProductItem) {
  return product.paidAmount + product.bonusAmount;
}

function ProductRow({ product }: { product: CloverProductItem }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{product.name}</span>
        <span className="inline-flex flex-wrap items-center gap-x-1 text-xs break-keep text-muted-foreground">
          <CloverIcon />
          클로버 {totalAmount(product).toLocaleString()}개
          {product.bonusAmount > 0 && <span>(보너스 {product.bonusAmount.toLocaleString()} 포함)</span>}
        </span>
      </div>
      <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums text-foreground">
        {product.priceKrw.toLocaleString()}원
      </span>
    </li>
  );
}

function UsageRow({ label, cost }: { label: string; cost: number }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <dt className="text-sm font-medium text-foreground">{label}</dt>
      <dd className="inline-flex items-center gap-1 text-sm whitespace-nowrap tabular-nums text-foreground">
        <CloverIcon />
        클로버 {cost.toLocaleString()}개
      </dd>
    </div>
  );
}

/** 진행 표시라 `motion-safe:`로 가두지 않는다(멈추면 "멈춘 UI"로 읽힌다 — `DESIGN.md` Motion 절). */
function PricingSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="h-7 w-24 animate-pulse rounded bg-muted" />
      <div className="flex flex-col gap-3">
        {["first", "second", "third"].map((key) => (
          <div key={key} className="h-16 animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
