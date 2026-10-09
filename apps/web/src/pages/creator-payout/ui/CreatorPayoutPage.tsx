import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, type RefObject } from "react";

import { ContentListEmptyState, ContentListLoadMore } from "@/entities/content";
import {
  creatorPayoutKeys,
  formatPayoutRate,
  formatStatementPeriod,
  isCreatorPayoutUnavailableError,
  toStatementsLoadMoreRecovery,
  useCreatorPayoutQuery,
  useCreatorPayoutStatementsQuery,
  type CreatorPayoutStatement,
} from "@/entities/creator-payout";
import { CreatorPayoutApplicationPanel } from "@/features/apply-creator-payout";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";
import { formatKrw } from "@/shared/lib/number/formatKrw";

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";

/** 크리에이터 정산 화면 — 신청·상태, 확정된 적립금, 확정 내역.
 *
 * 컨테이너 폭은 클로버 허브·마이페이지와 같은 `max-w-md`다. 섹션이 텍스트 몇 줄과 짧은 행뿐이라 같은 밀도이고, 내역
 * 행은 이름과 금액을 양 끝으로 벌리므로 컬럼을 넓혀도 그 사이 빈자리만 는다.
 *
 * 적립금과 내역은 승인된 적이 있을 때만 보인다(승인 취소 뒤에도 — 확정분이 남아 있다). 그 전에는 셀 것이 없다.
 * 지급 신청은 아직 열지 않았다 — 적립금 아래에 준비 중이라고만 말하고 버튼을 두지 않는다. 탈퇴하면 확정 적립금이
 * 사라진다는 것도 같은 자리에서 말한다 — 적립금이 보이는 곳에서 그것이 영구하지 않다는 사실을 함께 알린다. */
export function CreatorPayoutPage() {
  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">크리에이터 정산</h1>
        <CreatorPayoutIntro />
      </div>
      <CreatorPayoutBody />
    </main>
  );
}

/** 화면 머리 설명. 적립은 승인된 동안의 사용에만 쌓이므로(신청 전·반려·승인 취소 뒤에는 쌓이지 않는다) 조건절로
 * 말한다. 적립 비율은 서버 설정값(`rateBps`)이라 응답이 오기 전·실패하면 비율 문장을 빼고 정책 안내만 둔다 — 숫자를
 * 지어내지 않는다. 같은 쿼리를 본문과 함께 쓰므로 요청은 한 번이다.
 *
 * 화면을 연 채 정산이 꺼지면(503) 실패 뒤에도 앞서 받은 `data` 가 남는다. 본문이 "이용할 수 없어요"로 바뀌는데 머리가
 * 적립 비율을 말하면 서로 어긋나므로 그때는 비율 문장을 뺀다. */
function CreatorPayoutIntro() {
  const { data, error } = useCreatorPayoutQuery();
  const isUnavailable = isCreatorPayoutUnavailableError(error);
  return (
    <p className="text-sm break-keep text-muted-foreground">
      {data &&
        !isUnavailable &&
        `정산 승인을 받으면 다른 회원이 내 작품으로 대화하거나 소설을 만들 때 쓴 유료 클로버의 ${formatPayoutRate(data.rateBps)}가 적립돼요. `}
      정산 기준은{" "}
      <Link to={SUPPORT_DESTINATIONS["creator-payout-policy"].to} className={INLINE_LINK_CLASS}>
        {SUPPORT_DESTINATIONS["creator-payout-policy"].label}
      </Link>
      에서 볼 수 있어요.
    </p>
  );
}

function SectionHeading({ children }: { children: string }) {
  return <h2 className="text-xl font-semibold tracking-tight text-foreground">{children}</h2>;
}

function CreatorPayoutBody() {
  const query = useCreatorPayoutQuery();

  if (query.isPending) return <p className="text-sm text-muted-foreground">불러오는 중…</p>;

  // 스위치가 꺼진 것은 보이던 화면이 있어도 그 화면으로 바꾼다 — 더는 신청할 수 없다. 기다려도 풀리지 않아 다시 시도를
  // 권하지 않는다.
  if (query.isError && isCreatorPayoutUnavailableError(query.error)) {
    return <p className="text-sm break-keep text-muted-foreground">크리에이터 정산은 지금 이용할 수 없어요.</p>;
  }

  // 그 밖의 실패는 처음 불러오기에서만 오류 화면이다. 백그라운드 재조회(창 포커스 등)가 실패하면 이미 보이던 정보를 둔다.
  if (!query.data) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3">
        <p className="text-sm break-keep text-destructive-text">정산 정보를 불러오지 못했어요.</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  const payout = query.data;
  return (
    <>
      <section className="flex flex-col gap-4">
        <SectionHeading>정산 신청</SectionHeading>
        <CreatorPayoutApplicationPanel payout={payout} />
      </section>
      {payout.everApproved && <BalanceSection balanceKrw={payout.balanceKrw} />}
      {payout.everApproved && <StatementsSection />}
    </>
  );
}

function BalanceSection({ balanceKrw }: { balanceKrw: number }) {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>적립금</SectionHeading>
      <div className="flex flex-col gap-1">
        <span className="text-sm text-muted-foreground">확정된 적립금</span>
        <span className="text-xl font-semibold tabular-nums text-foreground">{formatKrw(balanceKrw)}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {/* 음수는 이미 확정한 적립의 원천 결제가 나중에 취소된 몫이다. 돌려받지 않고 앞으로의 적립에서 뺀다. */}
        {balanceKrw < 0 && (
          <p className="text-sm break-keep text-foreground">결제 취소 조정으로 다음 적립에서 차감돼요.</p>
        )}
        <p className="text-xs break-keep text-muted-foreground">
          확정된 적립만 보여요. 지난달 적립은 매달 3일에 확정돼 더해져요.
        </p>
        <p className="text-xs break-keep text-muted-foreground">
          지급 신청은 준비 중이에요. 탈퇴하면 확정된 적립금도 사라져요.
        </p>
      </div>
    </section>
  );
}

function StatementsSection() {
  const query = useCreatorPayoutStatementsQuery();
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLUListElement>(null);
  const statements = query.data?.pages.flatMap((page) => page.items) ?? [];

  const handleLoadMore = async () => {
    if (!query.hasNextPage || query.isFetchingNextPage) return;
    const result = await query.fetchNextPage();
    // 서버가 cursor 를 읽지 못하면 같은 cursor 로 다시 물어도 같다 — 처음부터 다시 읽는다.
    if (result.isError && toStatementsLoadMoreRecovery(result.error) === "restart") {
      await queryClient.resetQueries({ queryKey: creatorPayoutKeys.statements() });
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>정산 내역</SectionHeading>
      <StatementsBody
        query={query}
        statements={statements}
        listRef={listRef}
        onLoadMore={() => void handleLoadMore()}
      />
    </section>
  );
}

type StatementsBodyProps = {
  query: ReturnType<typeof useCreatorPayoutStatementsQuery>;
  statements: CreatorPayoutStatement[];
  listRef: RefObject<HTMLUListElement | null>;
  onLoadMore: () => void;
};

/** 클로버 내역과 같은 4갈래 순서 — 재시도 백오프 중에도 `isPending` 이라 `failureCount === 0` 으로 걸러야 이미 도착한
 * 목록이 로딩 문구에 갇히지 않는다. */
function StatementsBody({ query, statements, listRef, onLoadMore }: StatementsBodyProps) {
  if (query.isPending && query.failureCount === 0) {
    return <p className="text-sm text-muted-foreground">불러오는 중…</p>;
  }
  if (query.isError && statements.length === 0) {
    return (
      <p className="text-sm break-keep text-destructive-text">정산 내역을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
    );
  }
  if (statements.length === 0) {
    return <ContentListEmptyState message="아직 확정된 정산이 없어요. 지난달 적립은 매달 3일에 확정돼요." />;
  }

  return (
    <div className="flex flex-col gap-4">
      {/* "더 보기"가 실패했는지, 불러온 목록의 새로고침이 실패했는지에 따라 다시 할 일이 다르다. */}
      {query.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-sm break-keep text-destructive-text">
            {query.isFetchNextPageError
              ? "내역을 더 불러오지 못했어요."
              : "새로고침에 실패했어요. 보이는 내역이 최신이 아닐 수 있어요."}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={query.isFetchNextPageError ? onLoadMore : () => void query.refetch()}
          >
            다시 시도
          </Button>
        </div>
      )}

      {/* `tabIndex={-1}` — "더 보기"가 마지막 페이지에서 사라질 때 포커스를 여기로 넘긴다(`onExhausted`). */}
      <ul ref={listRef} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        {statements.map((statement) => (
          <StatementRow key={`${statement.kind}-${statement.windowStart}-${statement.windowEnd}`} statement={statement} />
        ))}
      </ul>

      <p className="text-xs break-keep text-muted-foreground">
        작품별 금액은 원 미만을 버린 값이라 더하면 정산액과 조금 다를 수 있어요.
      </p>

      <ContentListLoadMore
        hasMore={query.hasNextPage}
        isLoading={query.isFetchingNextPage}
        onLoadMore={onLoadMore}
        onExhausted={() => listRef.current?.focus()}
      />
    </div>
  );
}

/** 확정 하나. 머리 줄에 기간과 확정액을, 그 아래 작품별 내역을 둔다. 금액은 부호로만 방향을 말하고 색으로 가르지 않는다. */
function StatementRow({ statement }: { statement: CreatorPayoutStatement }) {
  const period = formatStatementPeriod(statement);
  const units =
    statement.refundedUnits > 0
      ? `유료 클로버 ${statement.grossUnits.toLocaleString("ko-KR")}개 사용 · ${statement.refundedUnits.toLocaleString("ko-KR")}개 환급`
      : `유료 클로버 ${statement.grossUnits.toLocaleString("ko-KR")}개 사용`;

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-medium text-foreground">{period.title}</span>
          <span className="text-xs break-keep text-muted-foreground">{period.range ?? units}</span>
          {period.range && <span className="text-xs break-keep text-muted-foreground">{units}</span>}
        </div>
        <span className="shrink-0 text-sm font-medium tabular-nums text-foreground">{formatKrw(statement.amountKrw)}</span>
      </div>
      {statement.lines.length > 0 && (
        <ul className="flex flex-col gap-1.5 border-t border-border pt-3">
          {statement.lines.map((line) => (
            <li key={line.contentId} className="flex items-start justify-between gap-3 text-xs">
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-foreground">{line.contentTitle}</span>
                {line.cancelAdjustKrw !== 0 && (
                  <span className="text-muted-foreground">결제 취소 조정 {formatKrw(line.cancelAdjustKrw)}</span>
                )}
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{formatKrw(line.amountKrw)}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
