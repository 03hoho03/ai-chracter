import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

/** `useQuery` 결과에서 이 컴포넌트가 읽는 것만. 오류 타입은 쿼리마다 달라(`ApiError` 등) 묶지 않는다. */
type QueryLike<T> = {
  data: T | undefined;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
  refetch: () => Promise<unknown>;
};

type QueryStateProps<T> = {
  query: QueryLike<T>;
  /** 스켈레톤이 놓이는 표면. `card`·`popover` 위에서는 `bg-muted` 가 같은 값이라 보이지 않아 `secondary` 로 칠한다. */
  surface?: "background" | "card";
  /** `detail` 은 `lg` 이상에서 상세의 조치 열 자리까지 그린다. */
  skeleton?: "block" | "detail";
  /** "작품 목록을 불러오지 못했어요." 처럼 무엇을 못 불러왔는지 말하는 한 문장. */
  errorMessage: string;
  isEmpty?: (data: T) => boolean;
  empty?: { title: string; action?: ReactNode };
  /**
   * 페이지를 넘기는 목록이면 응답의 페이지 정보(목록 응답 그대로 넘기면 된다). 요청한 페이지가 끝을 넘어 비어 오면 빈
   * 상태 대신 마지막 페이지(없으면 1페이지)로 URL 을 바꿔 다시 연다 — 기억해 둔 2페이지의 마지막 건을 상세에서 처리하고
   * "목록으로" 돌아오면 남은 항목이 1페이지에 다 들어가 2페이지가 비는데, 그대로 두면 "없어요"로 읽히고 페이지 버튼도
   * 없어 돌아갈 길이 없다. 페이지 search 키는 모든 목록이 `page` 다.
   */
  getPage?: (data: T) => { page: number; totalPages: number };
  children: (data: T) => ReactNode;
};

/**
 * 조회 상태 셋(로딩·오류·빈)을 한 모양으로 그린다. 오류에는 늘 "다시 시도"가 있다.
 *
 * 데이터가 있는 채 다시 불러오기가 실패하면 본문을 지우지 않고 위에 한 줄 오류를 얹는다 — 이전 페이지를 유지하는
 * 쿼리는 오류와 데이터가 함께 있는 순간이 있다.
 */
export function QueryState<T>({
  query,
  surface = "background",
  skeleton = "block",
  errorMessage,
  isEmpty,
  empty,
  getPage,
  children,
}: QueryStateProps<T>) {
  const fallbackPage = pastEndFallbackPage(query.data === undefined ? undefined : getPage?.(query.data));
  useFallBackToLastPage(fallbackPage);

  // 끝을 넘은 페이지는 곧 바뀔 화면이라 빈 상태를 한 번 보이지 않고 로딩으로 둔다.
  if (query.isPending || fallbackPage !== null) {
    // 진행 표시라 `motion-safe:` 로 가드하지 않는다 — 멈추면 "멈춘 화면"으로 읽힌다(DESIGN.md Motion 절).
    const fill = surface === "card" ? "bg-secondary" : "bg-muted";
    if (skeleton === "detail") {
      return (
        <div aria-busy className="grid gap-6 lg:grid-cols-[minmax(0,var(--container-3xl))_var(--container-2xs)]">
          <div className={cn("h-64 animate-pulse rounded-xl", fill)} />
          <div className={cn("hidden h-48 animate-pulse rounded-xl lg:block", fill)} />
        </div>
      );
    }
    return <div aria-busy className={cn("h-64 animate-pulse rounded-xl", fill)} />;
  }

  if (query.data === undefined) {
    return <QueryError message={errorMessage} query={query} />;
  }

  const data = query.data;
  const body = isEmpty?.(data) && empty ? <EmptyState title={empty.title} action={empty.action} /> : children(data);

  // 오류 줄이 있든 없든 본문 자리를 같게 둔다 — 모양이 바뀌면 다시 불러오기가 실패하는 순간 본문이 통째로 다시
  // 마운트돼 그 안의 상태(고른 항목, 적던 입력)와 포커스를 잃는다.
  return (
    <>
      {query.isError && <QueryError message={errorMessage} query={query} />}
      {body}
    </>
  );
}

function pastEndFallbackPage(pageInfo: { page: number; totalPages: number } | undefined) {
  if (pageInfo === undefined || pageInfo.page <= 1 || pageInfo.page <= pageInfo.totalPages) return null;
  return Math.max(pageInfo.totalPages, 1);
}

/** URL 이 상태의 소스라 라우터를 바꿔 따라가게 하는 동기화다. 기록을 바꿔치기해 뒤로가기가 빈 페이지로 되돌아가지 않게 한다. */
function useFallBackToLastPage(fallbackPage: number | null) {
  const navigate = useNavigate();
  useEffect(() => {
    if (fallbackPage === null) return;
    void navigate({ to: ".", search: (prev) => ({ ...prev, page: fallbackPage }), replace: true });
  }, [fallbackPage, navigate]);
}

function QueryError<T>({ message, query }: { message: string; query: QueryLike<T> }) {
  const isRetrying = query.isFetching;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p role="alert" className="break-keep text-sm text-destructive-text">
        {message}
      </p>
      {/* 다시 시도 중에도 `disabled` 를 쓰지 않는다 — 누른 버튼이 포커스를 잃는다. 대신 진행 중이면 눌러도 무시한다:
          `refetch()` 는 진행 중인 요청을 취소하고 새로 보내서, 연타하면 요청이 겹겹이 나간다. */}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={isRetrying}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isRetrying) return;
          void query.refetch();
        }}
      >
        {isRetrying ? "다시 시도하는 중…" : "다시 시도"}
      </Button>
    </div>
  );
}

function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-border px-4 py-8 sm:px-6">
      <p className="break-keep text-sm text-muted-foreground">{title}</p>
      {action}
    </div>
  );
}
