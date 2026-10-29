import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import type { CloverPricingResponse, CloverProductsResponse } from "@/entities/clover";

import { formatRefundSentences, formatValiditySentences, MINOR_PAYMENT_SENTENCE } from "../model/cloverPolicy";
import { HubSection } from "./HubSection";

type CloverFaqProps = {
  /** 상품 응답. 정책 숫자(유효기간·환불 날수·비율)가 여기서 오므로, 없으면 항목을 그리지 않는다. */
  products: CloverProductsResponse | undefined;
  isError: boolean;
  /** 공개 가격 응답의 출석판 정책. 못 받았으면 비워 둔다 — 출석 클로버 항목의 숫자가 여기서 오므로 그때는 그 항목만
   * 그리지 않는다. */
  attendance: CloverPricingResponse["attendance"] | undefined;
};

/** 클로버 안내 — 기본 접힘. 항목 머리는 이용약관·환불정책과 같은 절 이름을 써 찾기 쉽게 한다. 펼친 상태는 저장하지
 * 않는다(다시 오면 접혀 있다).
 *
 * 숫자가 든 정책 문장은 상품 응답의 `policy` 로 만든다(웹에 숫자 사본이 없다). 응답이 오기 전에는 제목만 두고, 받지
 * 못했으면 다시 시도를 따로 두지 않고 충전 상품 섹션의 버튼을 가리킨다 — 같은 요청 하나다(그 섹션은 좁은 화면에서는
 * 위, 넓은 화면에서는 같은 열 위라 문구에 방향을 적지 않는다). */
export function CloverFaq({ products, isError, attendance }: CloverFaqProps) {
  return (
    <HubSection title="클로버 안내">
      {isError && !products && (
        <p className="text-sm break-keep text-muted-foreground">
          안내는 상품 정보와 함께 불러와요. 충전 상품에서 다시 시도해 주세요.
        </p>
      )}
      {products && (
        <div className="flex flex-col gap-1">
          <FaqItem title="유효기간과 사용 순서">
            <PolicyList items={formatValiditySentences(products.policy)} />
          </FaqItem>
          {attendance && (
            <FaqItem title="출석 클로버">
              <p className="text-sm break-keep text-foreground">
                출석 클로버는 받은 날부터 {attendance.minValidDays}일 동안 쓸 수 있어요. 하루 한 번, 한국 시간 자정에 새로
                받아요.
              </p>
            </FaqItem>
          )}
          <FaqItem title="청약철회와 환불">
            {/* 환불정책 링크는 구매 조건에 하나만 둔다 — 같은 이름·같은 목적지 링크가 한 화면에 둘이면 화면 읽기
                프로그램의 링크 목록에 같은 항목이 두 번 나온다. */}
            <PolicyList items={formatRefundSentences(products.policy)} />
          </FaqItem>
          <FaqItem title="미성년자 결제">
            <p className="text-sm break-keep text-foreground">{MINOR_PAYMENT_SENTENCE}</p>
          </FaqItem>
        </div>
      )}
    </HubSection>
  );
}

/** 접는 항목 하나. 머리는 `<h3>` 안의 버튼 하나다(버튼 안에 다른 버튼·링크를 두지 않는다). 본문은 `hidden` 이라 접힌
 * 동안 탭 순서와 읽기 순서에서 빠진다. 카드 없는 섹션의 접기 관용구대로 hover 면은 머리 줄만큼 바깥으로 넓히고(`-mx-2`),
 * 그 면 위 글자는 `foreground` 다(라이트 `secondary` 위 `muted-foreground` 는 대비가 모자란다). 셰브런은 펼침 전이 없이
 * 바로 뒤집힌다. */
function FaqItem({ title, children }: { title: string; children: ReactNode }) {
  const bodyId = useId();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="flex flex-col">
      <h3 className="flex flex-col">
        <button
          type="button"
          aria-expanded={isOpen}
          aria-controls={bodyId}
          onClick={() => setIsOpen((open) => !open)}
          className="-mx-2 flex min-h-9 items-center justify-between gap-3 rounded-lg border border-transparent px-2 text-left text-sm font-medium text-foreground outline-none hover:bg-secondary focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
        >
          {title}
          <ChevronDown aria-hidden className={cn("size-4 shrink-0 text-muted-foreground", isOpen && "rotate-180")} />
        </button>
      </h3>
      <div id={bodyId} hidden={!isOpen} className="flex flex-col gap-3 pt-2 pb-3">
        {children}
      </div>
    </div>
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
