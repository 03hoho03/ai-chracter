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
  CloverIcon,
  CloverProductLine,
  useCloverPricingQuery,
  type CloverPricingResponse,
  type CloverProductItem,
} from "@/entities/clover";
import { CONTACT_EMAIL } from "@/shared/config/site";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import { formatTrialSentence } from "../model/trialSentence";

const INLINE_LINK_CLASSNAME =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

/** 사용처 단가 목록과 무료 대화 수는 가격 응답에 나중에 더한 필드다. */
type AddedPricingKey = "models" | "novelAiEditCost" | "novelRestricted" | "dailyFreeChatTurns";

/** 이 화면이 읽는 가격 응답. web 과 API 는 따로 배포돼 새 화면이 옛 API 의 응답(위 필드가 없다)을 받는 구간이 있다.
 * 타입은 그 필드를 필수로 적지만 그 구간에는 런타임에 비어 있으므로, 화면은 이 모양으로 읽고 빈 필드를 건너뛴다. */
type DeployedPricingResponse = Omit<CloverPricingResponse, AddedPricingKey> &
  Partial<Pick<CloverPricingResponse, AddedPricingKey>>;

type ModelPricing = CloverPricingResponse["models"][number];

/** 허용된 계정만 쓰는 사용처에 붙이는 표시. 아래 각주가 뜻을 풀어 준다. */
const RESTRICTED_LABEL = "일부 계정만";

/** `/clover/pricing` — 로그인 없이 보는 클로버 상품 안내.
 *
 * 가격·수량·단가 숫자는 전부 `GET /clover/pricing` 응답에서 온다. 이 파일에 숫자를 적으면 상품을 바꿀 때
 * 서버와 화면이 갈린다. 반면 유효기간·7일·환불 비율·사용 순서는 정책 문장이라 여기 적고, 같은 문장이
 * 이용약관과 환불정책(둘 다 DB 게시본)에도 있다 — 셋 중 하나를 고치면 나머지와 함께 맞춘다.
 *
 * 컨테이너는 클로버 허브와 같은 `max-w-md` 한 열이다. 텍스트 몇 줄과 짧은 행뿐이라 넓혀도 행 가운데 빈자리만
 * 는다. 구매는 로그인한 클로버 허브에서 하므로, 결제가 열려 있으면(`paymentsEnabled`) 상품 행 자체가 허브로 가는
 * 링크이고 허브가 그 상품의 구매 확인을 바로 연다. 열리지 않은 동안은 행이 정보일 뿐이다 — 할 수 없는 동작을
 * 약속하지 않는다.
 */
export function CloverPricingPage() {
  // 정책 문장 하나가 게이트 스위치와 무료 대화 수로 갈린다(`formatTrialSentence`). 같은 가격 쿼리라 아래 상품 목록과
  // 요청은 하나다.
  const pricing: DeployedPricingResponse | undefined = useCloverPricingQuery().data;

  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {SUPPORT_DESTINATIONS["clover-pricing"].label}
        </h1>
        <p className="text-sm break-keep text-muted-foreground">클로버는 대화, 소설, 이미지 생성에 쓰여요.</p>
      </div>

      <PricingBody />

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
          미성년자가 법정대리인의 동의 없이 결제했다면 본인이나 법정대리인이 취소할 수 있어요. 다만 성년자이거나
          법정대리인이 동의한 것처럼 속였거나, 용돈처럼 법정대리인이 쓰도록 허락한 돈의 범위에서 결제했다면 취소할 수
          없어요.
        </p>
      </Section>
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
 * "충전 상품" 제목은 로딩·실패·성공 어느 상태에서나 같은 자리에 남는다 — 실패할 때 제목까지 사라지면 이 화면에 상품
 * 안내가 있다는 사실이 함께 사라진다. 다시 시도를 누르면 쿼리가 로딩 상태로 돌아가 실패 패널(과 그 버튼)이 언마운트되므로,
 * 누르는 즉시 포커스를 남아 있는 제목으로 옮긴다(안 그러면 포커스가 `<body>`로 떨어진다). 세 상태가 같은 트리
 * 모양이라(첫 자식이 이 섹션) 제목은 다시 마운트되지 않는다. */
function PricingBody() {
  const pricingQuery = useCloverPricingQuery();
  const productsHeadingRef = useRef<HTMLHeadingElement>(null);
  const pricing: DeployedPricingResponse | undefined = pricingQuery.isSuccess ? pricingQuery.data : undefined;

  return (
    <>
      <Section title="충전 상품" headingRef={productsHeadingRef}>
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
      {pricing && (
        <Section title="쓰임새">
          <UsageCosts pricing={pricing} />
        </Section>
      )}
    </>
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
          ? "가격은 부가세 포함이에요. 상품을 누르면 클로버 화면에서 바로 구매를 이어 갈 수 있어요."
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
      <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

/** 사용처별 단가. 대화와 소설은 모델마다 값이 달라 모델 × 사용처 표로, 이미지와 AI 수정은 모델과 무관해 한 줄씩 둔다.
 * 허용된 계정만 쓰는 사용처(상위 모델, 소설)는 숨기지 않고 표시를 붙여 싣는다 — 구매 전 안내에 없는 사용처 가격은
 * 숨은 가격으로 읽힌다. 행을 상자로 감싸지 않고 선으로만 가른다(누르는 것이 아니다).
 *
 * 모델 목록이 없는 응답(사용처 단가를 싣기 전의 옛 API)이면 기본 모델 대화 단가 한 줄로 돌아간다. */
function UsageCosts({ pricing }: { pricing: DeployedPricingResponse }) {
  const models = pricing.models ?? [];
  const isNovelRestricted = pricing.novelRestricted ?? false;
  const hasRestricted = isNovelRestricted || models.some((model) => model.restricted);
  const [exampleProduct] = pricing.products;
  const exampleAmount = exampleProduct ? exampleProduct.paidAmount + exampleProduct.bonusAmount : 0;

  return (
    <>
      {models.length > 0 && <ModelCostTable models={models} isNovelRestricted={isNovelRestricted} />}
      <dl className="flex flex-col divide-y divide-border border-y border-border">
        {models.length === 0 && <UsageRow label="대화 1턴" cost={pricing.chatTurnCost} />}
        <UsageRow label="이미지 1장" cost={pricing.imageCost} />
        {pricing.novelAiEditCost !== undefined && (
          <UsageRow label="소설 AI 수정 1회" cost={pricing.novelAiEditCost} isRestricted={isNovelRestricted} />
        )}
      </dl>
      {hasRestricted && (
        <p className="text-xs break-keep text-muted-foreground">
          ‘{RESTRICTED_LABEL}’ 기능은 아직 열어 둔 계정에서만 쓸 수 있어요.
        </p>
      )}
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
 * 읽는다. 값 칸은 클로버 개수이고 오른쪽 정렬 `tabular-nums` 로 자릿수를 세로로 맞춘다. 정보 표라 행 hover 를 끈다. */
function ModelCostTable({ models, isNovelRestricted }: { models: readonly ModelPricing[]; isNovelRestricted: boolean }) {
  return (
    <Table>
      <caption className="sr-only">모델별 클로버 단가</caption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="col" className="pl-0 align-bottom">
            모델
          </TableHead>
          <TableHead scope="col" className="text-right align-bottom">
            대화 1턴
          </TableHead>
          <TableHead scope="col" className="h-auto py-2 pr-0 text-right align-bottom">
            <span className="flex flex-col items-end">
              소설 1화
              {isNovelRestricted && <RestrictedNote />}
            </span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {models.map((model) => (
          <TableRow key={model.id} className="hover:bg-transparent">
            <TableHead scope="row" className="h-auto py-3 pl-0 font-medium">
              <span className="flex flex-col">
                {model.name}
                {model.restricted ? (
                  <RestrictedNote />
                ) : (
                  model.isDefault && <span className="text-xs font-normal text-muted-foreground">기본 모델</span>
                )}
              </span>
            </TableHead>
            <TableCell className="text-right">
              <CloverCost cost={model.chatTurnCost} />
            </TableCell>
            <TableCell className="pr-0 text-right">
              <CloverCost cost={model.novelEpisodeCost} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RestrictedNote() {
  return <span className="text-xs font-normal text-muted-foreground">{RESTRICTED_LABEL}</span>;
}

function CloverCost({ cost }: { cost: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-sm whitespace-nowrap tabular-nums text-foreground">
      <CloverIcon />
      {cost.toLocaleString()}개
    </span>
  );
}

function UsageRow({ label, cost, isRestricted = false }: { label: string; cost: number; isRestricted?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <dt className="flex flex-col text-sm font-medium text-foreground">
        {label}
        {isRestricted && <RestrictedNote />}
      </dt>
      <dd>
        <CloverCost cost={cost} />
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
