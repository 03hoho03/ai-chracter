import { Button } from "@ai-character-chat/ui/components/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useRef, type ReactNode, type Ref } from "react";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  CloverProductLine,
  useCloverPricingQuery,
  type CloverPricingResponse,
  type CloverProductItem,
} from "@/entities/clover";
import { CONTACT_EMAIL } from "@/shared/config/site";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import { formatFreeChatSentence } from "../model/freeChatSentence";
import { formatTrialSentence } from "../model/trialSentence";

const INLINE_LINK_CLASSNAME =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

/** 사용처 단가 목록과 무료 대화 수는 가격 응답에 나중에 더한 필드다. */
type AddedPricingKey = "models" | "novelAiEditCost" | "dailyFreeChatTurns";

/** 이 화면이 읽는 가격 응답. web 과 API 는 따로 배포돼 새 화면이 옛 API 의 응답(위 필드가 없다)을 받는 구간이 있다.
 * 타입은 그 필드를 필수로 적지만 그 구간에는 런타임에 비어 있으므로, 화면은 이 모양으로 읽고 빈 필드를 건너뛴다. */
type DeployedPricingResponse = Omit<CloverPricingResponse, AddedPricingKey> &
  Partial<Pick<CloverPricingResponse, AddedPricingKey>>;

type ModelPricing = CloverPricingResponse["models"][number];

/** `/clover/pricing` — 로그인 없이 보는 클로버 상품 안내.
 *
 * 가격·수량·단가 숫자는 전부 `GET /clover/pricing` 응답에서 온다. 이 파일에 숫자를 적으면 상품을 바꿀 때
 * 서버와 화면이 갈린다. 반면 유효기간·7일·환불 비율·사용 순서는 정책 문장이라 여기 적고, 같은 문장이
 * 이용약관과 환불정책(둘 다 DB 게시본)에도 있다 — 셋 중 하나를 고치면 나머지와 함께 맞춘다.
 *
 * 컨테이너는 이 화면이 가리키는 환불정책(법적 문서 화면)·공지와 같은 문서 폭 `max-w-2xl` 한 열이고, `lg` 이상에서만
 * `max-w-4xl`로 넓혀 상품과 쓰임새를 두 열로 나란히 둔다 — 상품의 클로버 수와 사용처 단가를 한눈에 견줄 수 있다.
 * 그 아래 정책 문장은 넓어진 폭을 따라 늘이지 않고 `max-w-prose`(65ch)에 묶어 한 줄 길이를 문서 화면과 같게 둔다.
 *
 * 구매는 로그인한 클로버 허브에서 하므로, 결제가 열려 있으면(`paymentsEnabled`) 상품 행 자체가 허브로 가는
 * 링크이고 허브가 그 상품의 구매 확인을 바로 연다. 열리지 않은 동안은 행이 정보일 뿐이다 — 할 수 없는 동작을
 * 약속하지 않는다.
 */
export function CloverPricingPage() {
  // 정책 문장 하나가 게이트 스위치와 무료 대화 수로 갈린다(`formatTrialSentence`). 같은 가격 쿼리라 아래 상품 목록과
  // 요청은 하나다.
  const pricing: DeployedPricingResponse | undefined = useCloverPricingQuery().data;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-10 px-4 sm:px-6 py-10 lg:max-w-4xl">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {SUPPORT_DESTINATIONS["clover-pricing"].label}
        </h1>
        <p className="text-sm break-keep text-muted-foreground">클로버는 대화, 소설, 이미지 생성에 쓰여요.</p>
      </div>

      <PricingBody />

      <div className="flex max-w-prose flex-col gap-10">
        <Section title="유효기간과 사용 순서">
          <PolicyList
            items={[
              "유료 클로버와 보너스 클로버는 구매일로부터 5년 동안 쓸 수 있어요.",
              CLOVER_EXPIRY_NOTICE_MESSAGE,
              "클로버는 무료, 보너스, 유료 순서로 쓰여요. 무료 클로버는 환불되지 않아요.",
              "본인인증 기능이 열리면, 미션 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.",
            ]}
          />
        </Section>

        <Section title="청약철회와 환불">
          <PolicyList
            items={[
              "결제일로부터 7일 안에는 쓰지 않은 유료 클로버를 전액 돌려받을 수 있어요. 이미 쓴 보너스 클로버만큼은 빼고 돌려드려요.",
              "7일이 지나도 남은 유료 클로버를 환불받을 수 있어요. 이때도 이미 쓴 보너스 클로버만큼은 빼고, 그 금액의 90%를 돌려드려요.",
              "이미 쓴 클로버는 청약철회할 수 없어요. 클로버는 쓰는 즉시 기능 이용에 제공되기 때문이에요.",
              formatTrialSentence(pricing?.identityGateEnabled ?? false, pricing?.dailyFreeChatTurns),
              "보너스 클로버는 따로 환불되지 않아요. 유료 클로버를 환불하면 그 구매로 받은 보너스 클로버 중 남은 것은 회수돼요.",
              "탈퇴하면 남은 클로버가 모두 사라져요. 남은 유료 클로버는 탈퇴하기 전에 환불을 신청해주세요.",
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
            클로버는 <span className="whitespace-nowrap">만 19세</span> 이상만 살 수 있어요. 그래도 미성년자가 법정대리인의 동의 없이 결제했다면 본인이나 법정대리인이 취소할 수 있어요. 다만 성년자이거나
            법정대리인이 동의한 것처럼 속였거나, 용돈처럼 법정대리인이 쓰도록 허락한 돈의 범위에서 결제했다면 취소할 수
            없어요.
          </p>
        </Section>
      </div>
    </main>
  );
}

function Section({
  title,
  headingRef,
  children,
}: {
  title: string;
  /** 주면 제목이 프로그램 포커스를 받을 수 있다(`tabIndex={-1}`). */
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <h2
        ref={headingRef}
        tabIndex={headingRef ? -1 : undefined}
        className="text-xl font-semibold tracking-tight text-foreground"
      >
        {title}
      </h2>
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
 * 바깥에 둔다(`pages/legal-document`의 관용구 — 실패해도 환불 조건은 읽힌다).
 *
 * "충전 상품"·"쓰임새" 두 제목은 로딩·실패·성공 어느 상태에서나 같은 자리에 남는다 — 실패할 때 제목까지 사라지면 이
 * 화면에 상품과 단가 안내가 있다는 사실이 함께 사라진다. 쓰임새는 다시 시도 버튼을 따로 두지 않고 충전 상품 섹션의
 * 버튼을 가리킨다(같은 요청 하나다. 그 섹션은 좁은 화면에서는 위, `lg` 이상에서는 왼쪽이라 문구에 방향을 적지 않는다). 다시 시도를 누르면 쿼리가 로딩 상태로 돌아가 실패 패널(과 그 버튼)이 언마운트되므로,
 * 누르는 즉시 포커스를 남아 있는 제목으로 옮긴다(안 그러면 포커스가 `<body>`로 떨어진다). 세 상태가 같은 트리
 * 모양이라(첫 자식이 이 섹션) 제목은 다시 마운트되지 않는다.
 *
 * `lg` 이상에서는 두 섹션이 두 열로 선다. 각 열은 위에서부터 채우고(`items-start`) 서로 높이를 맞추지 않는다 — 늘어난
 * 쪽에 빈 바닥이 생겨도 그리는 상자가 없어 보이지 않는다. 좁은 화면에서는 지금처럼 상품 → 쓰임새 순서의 한 열이다. */
function PricingBody() {
  const pricingQuery = useCloverPricingQuery();
  const productsHeadingRef = useRef<HTMLHeadingElement>(null);
  const pricing: DeployedPricingResponse | undefined = pricingQuery.isSuccess ? pricingQuery.data : undefined;

  return (
    <div className="grid items-start gap-10 lg:grid-cols-2 lg:gap-12">
      <Section title="충전 상품" headingRef={productsHeadingRef}>
        {/* 구매 자격은 상품을 고르기 전에 읽혀야 해 제목 바로 아래에 둔다. 서버의 주문 생성 판정 그대로다 — 본인인증은
            나이를 확인하는 유일한 수단이라 미인증 회원 게이트 스위치와 무관하게 늘 필요하고, 그 뒤 만 19세 미만을
            막는다. 그래서 게이트 값으로 가르지 않는다. 결제가 닫혀 있으면 살 수 없다는 말이 먼저라 싣지 않는다. */}
        {pricing?.paymentsEnabled && (
          <p className="text-sm break-keep text-foreground">
            휴대폰 본인인증을 마친 <span className="whitespace-nowrap">만 19세</span> 이상 회원만 살 수 있어요.
          </p>
        )}
        {pricingQuery.isPending && <ProductListSkeleton />}
        {pricingQuery.isError && (
          <PricingErrorState
            onRetry={() => {
              productsHeadingRef.current?.focus();
              void pricingQuery.refetch();
            }}
          />
        )}
        {pricing && <ProductList products={pricing.products} paymentsEnabled={pricing.paymentsEnabled} />}
      </Section>
      <Section title="쓰임새">
        {pricingQuery.isPending && <div className="h-40 animate-pulse rounded-xl bg-muted" />}
        {pricingQuery.isError && (
          <p className="text-sm break-keep text-muted-foreground">
            사용처별 단가는 상품 정보와 함께 불러와요. 충전 상품에서 다시 시도해주세요.
          </p>
        )}
        {pricing && <UsageCosts pricing={pricing} />}
      </Section>
    </div>
  );
}

function ProductList({
  products,
  paymentsEnabled,
}: {
  products: readonly CloverProductItem[];
  paymentsEnabled: boolean;
}) {
  if (products.length === 0) {
    return (
      <EmptyPanel>
        <p className="text-sm text-muted-foreground">지금 판매 중인 클로버 상품이 없어요.</p>
      </EmptyPanel>
    );
  }

  return (
    <>
      {paymentsEnabled ? (
        <ul className="flex flex-col gap-3">
          {products.map((product) => (
            <li key={product.key}>
              <ProductLink product={product} />
            </li>
          ))}
        </ul>
      ) : (
        // 누를 수 없는 행은 테두리 상자로 감싸지 않는다 — 허브의 누르는 상품 카드와 같은 모양이면 눌러도 반응이 없는
        // 카드로 읽힌다. 선 하나로만 행을 가른다.
        <ul className="flex flex-col divide-y divide-border border-y border-border">
          {products.map((product) => (
            <li key={product.key} className="flex items-center justify-between gap-3 py-3">
              <CloverProductLine product={product} />
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs break-keep text-muted-foreground">
        {paymentsEnabled
          ? "가격은 부가세 포함이에요. 상품을 누르면 클로버 화면에서 구매를 이어 가요. 로그인 전이라면 로그인한 뒤에 이어져요."
          : "가격은 부가세 포함이에요. 클로버 결제는 아직 준비 중이에요."}
      </p>
    </>
  );
}

/** 상품 행 전체가 허브로 가는 링크다. 허브가 `product` 로 그 상품의 구매 확인을 연다(로그인하지 않았으면 로그인한 뒤
 * 같은 주소로 돌아온다). 껍데기는 허브의 상품 버튼과 같은 button-outline 레시피를 카드 크기로 쓴다 — 두 화면에서
 * 같은 상품 행이 같은 모양으로 눌린다. 다른 화면으로 넘어가는 행이라 끝에 셰브런을 둔다. */
function ProductLink({ product }: { product: CloverProductItem }) {
  return (
    <Link
      to="/clover"
      search={{ product: product.key }}
      className="flex min-h-11 w-full items-center gap-2 rounded-xl border border-border bg-background py-3 pr-3 pl-4 outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px motion-safe:transition-colors"
    >
      <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
        <CloverProductLine product={product} />
      </span>
      {/* 보이는 내용만으로는 접근 이름이 상품 정보뿐이라 누르면 어디로 가는지 모른다. 보이는 글자를 이름에 그대로 두고
          목적지만 덧붙인다(`aria-label` 로 덮으면 보이는 글자와 읽는 이름이 갈린다). */}
      <span className="sr-only">구매하러 가기</span>
      <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

/** 사용처별 단가. 대화와 소설은 모델마다 값이 달라 모델 × 사용처 표로, 이미지와 AI 수정은 모델과 무관해 한 줄씩 둔다.
 * 응답에 실린 사용처는 전부 같은 모양으로 싣는다. 행을 상자로 감싸지 않고 선으로만 가른다(누르는 것이 아니다).
 *
 * 모델 목록이 없는 응답(사용처 단가를 싣기 전의 옛 API)이면 기본 모델 대화 단가 한 줄로 돌아간다. */
function UsageCosts({ pricing }: { pricing: DeployedPricingResponse }) {
  const models = pricing.models ?? [];
  const [exampleProduct] = pricing.products;
  const exampleAmount = exampleProduct ? exampleProduct.paidAmount + exampleProduct.bonusAmount : 0;
  const freeChatSentence = formatFreeChatSentence(
    pricing.identityGateEnabled,
    pricing.dailyFreeChatTurns,
    pricing.chatTurnCost,
  );

  return (
    <>
      {/* 클로버 없이 쓸 수 있는 부분을 단가보다 먼저 말한다 — 표만 보면 첫 턴부터 클로버가 드는 것으로 읽힌다. */}
      {freeChatSentence && <p className="text-sm break-keep text-foreground">{freeChatSentence}</p>}
      {models.length > 0 && <ModelCostTable models={models} />}
      <dl className="flex flex-col divide-y divide-border border-y border-border">
        {models.length === 0 && <UsageRow label="대화 1턴" cost={pricing.chatTurnCost} />}
        <UsageRow label="이미지 1장" cost={pricing.imageCost} />
        {pricing.novelAiEditCost !== undefined && (
          <UsageRow label="소설 AI 수정 1회" cost={pricing.novelAiEditCost} />
        )}
      </dl>
      {/* 단가가 0이면 나눗셈이 무한대가 된다 — 그때는 예시를 싣지 않는다. */}
      {exampleAmount > 0 && pricing.chatTurnCost > 0 && pricing.imageCost > 0 && (
        <p className="text-sm break-keep text-foreground">
          예를 들어 클로버 {exampleAmount.toLocaleString()}개로 기본 모델 대화를{" "}
          {Math.floor(exampleAmount / pricing.chatTurnCost).toLocaleString()}턴 하거나 이미지를{" "}
          {Math.floor(exampleAmount / pricing.imageCost).toLocaleString()}장 만들 수 있어요.{" "}
          <span className="text-muted-foreground">이해를 돕기 위한 예시예요.</span>
        </p>
      )}
    </>
  );
}

/** 모델 × 사용처(대화 1턴, 소설 1화) 단가 표. 두 사용처가 같은 모델 목록을 공유하므로 표로 묶으면 모델 이름을 한 번만
 * 읽는다. 값 칸은 클로버 개수이고, 단위는 칸마다 아이콘을 되풀이하지 않고 열 머리에 한 번 적는다. 오른쪽 정렬
 * `tabular-nums` 로 자릿수를 세로로 맞춘다. 정보 표라 행 hover 를 끈다. */
function ModelCostTable({ models }: { models: readonly ModelPricing[] }) {
  return (
    <Table>
      <caption className="sr-only">모델별 클로버 단가</caption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="col" className="pl-0 align-bottom">
            모델
          </TableHead>
          <TableHead scope="col" className="h-auto py-2 text-right align-bottom">
            <ColumnHeading label="대화 1턴" />
          </TableHead>
          <TableHead scope="col" className="h-auto py-2 pr-0 text-right align-bottom">
            <ColumnHeading label="소설 1화" />
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {models.map((model) => (
          <TableRow key={model.id} className="hover:bg-transparent">
            <TableHead scope="row" className="h-auto py-3 pl-0 align-top font-medium">
              <span className="flex flex-col">
                {model.name}
                {model.isDefault && <span className="text-xs font-normal text-muted-foreground">기본 모델</span>}
              </span>
            </TableHead>
            <TableCell className="py-3 text-right align-top">
              <CostValue>{model.chatTurnCost.toLocaleString()}</CostValue>
            </TableCell>
            <TableCell className="py-3 pr-0 text-right align-top">
              <CostValue>{model.novelEpisodeCost.toLocaleString()}</CostValue>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ColumnHeading({ label }: { label: string }) {
  return (
    <span className="flex flex-col items-end">
      {label}
      <span className="text-xs font-normal text-muted-foreground">클로버</span>
    </span>
  );
}

function CostValue({ children }: { children: ReactNode }) {
  return <span className="text-sm whitespace-nowrap tabular-nums text-foreground">{children}</span>;
}

function UsageRow({ label, cost }: { label: string; cost: number }) {
  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <dt className="text-sm font-medium text-foreground">{label}</dt>
      <dd>
        <CostValue>클로버 {cost.toLocaleString()}개</CostValue>
      </dd>
    </div>
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

/** 가격 응답을 못 받았을 때. 위험한 동작이 아니라 `destructive` 글자를 쓰지 않는다(아래 정책 문장 위에 빨간 글자가
 * 뜨면 정책이 틀린 것처럼 읽힌다). 다시 시도는 이 패널의 유일한 앞길이라 기본 크기 버튼이다. */
function PricingErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <EmptyPanel>
      <div role="alert" className="flex flex-col gap-1.5">
        <p className="text-lg font-semibold text-foreground">상품 정보를 불러오지 못했어요</p>
        <p className="text-sm text-muted-foreground">
          계속 안 되면{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className={INLINE_LINK_CLASSNAME}>
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
    <div className="flex flex-col gap-3">
      {["first", "second", "third"].map((key) => (
        <div key={key} className="h-16 animate-pulse rounded-xl bg-muted" />
      ))}
    </div>
  );
}
