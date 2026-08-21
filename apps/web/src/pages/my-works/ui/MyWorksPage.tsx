import { Button } from "@ai-character-chat/ui/components/button";
import { useNavigate } from "@tanstack/react-router";

import {
  ContentCard,
  ContentListEmptyState,
  useProfileContentListQuery,
  type ContentCardTag,
} from "@/entities/content";
import { useDraftListQuery } from "@/entities/draft";
import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";

import { formatMyWorkUpdatedAt, mergeMyWorks, type MyWorkItem } from "../model/myWorkItems";

/** prd-creator-entry-and-my-works.md US-008 — 발행 여부와 상관없이 내가 만든 것을 한 화면에서 본다.
 * 서버에는 둘을 합쳐 주는 엔드포인트가 없어 캐릭터·스토리 발행작(`GET /users/{me}/contents`)과
 * 초안(`GET /me/drafts`)을 각각 받아 클라이언트에서 병합한다(확정 결정 9). */
export function MyWorksPage({ userId }: { userId: string }) {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">내 작품</h1>

      <MyWorksBody userId={userId} />
    </main>
  );
}

/** 세 쿼리를 합치는 화면이라 상태가 배타적이지 않다 — 하나는 실패하고 하나는 아직 로딩일 수 있다.
 * 그래서 조건부 렌더 나열이 아니라 early return으로 순서를 강제하고, **일부만 실패하면 성공한 목록은
 * 그대로 보여준다**(안 그러면 초안 엔드포인트 하나가 흔들릴 때 발행작 32건이 함께 사라진다 — 실측). */
function MyWorksBody({ userId }: { userId: string }) {
  const characterQuery = useProfileContentListQuery({ userId, type: "character" });
  const storyQuery = useProfileContentListQuery({ userId, type: "story" });
  const draftListQuery = useDraftListQuery();

  const queries = [characterQuery, storyQuery, draftListQuery];
  const failedQueries = queries.filter((query) => query.isError);

  const retryFailed = () => {
    for (const query of failedQueries) query.refetch();
  };

  if (failedQueries.length === queries.length) {
    return <MyWorksFullErrorState onRetry={retryFailed} />;
  }

  // `failureCount === 0`을 함께 보는 이유: 한 번이라도 실패해 재시도 백오프에 들어간 쿼리는 그동안 계속
  // `isPending`이라, 그것만 보면 이미 도착한 발행작 32건이 **7.07초**(retry 3회 1s→2s→4s) 동안 스켈레톤
  // 뒤에 갇힌다(실측). 첫 실패 순간 스켈레톤을 걷고, 백오프가 끝나 `isError`가 되면 아래 알림 배너가 붙는다.
  if (queries.some((query) => query.isPending && query.failureCount === 0)) return <MyWorksSkeleton />;

  const items = mergeMyWorks(
    [...(characterQuery.data ?? []), ...(storyQuery.data ?? [])],
    draftListQuery.data ?? [],
  );

  if (items.length === 0) return <ContentListEmptyState message="아직 만든 작품이 없어요." />;

  return (
    <div className="flex flex-col gap-4">
      {failedQueries.length > 0 && (
        <MyWorksErrorState
          message={
            draftListQuery.isError
              ? "초안을 불러오지 못했어요. 발행한 작품만 보여주고 있어요."
              : "일부 작품을 불러오지 못했어요."
          }
          onRetry={retryFailed}
        />
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {items.map((item, index) => (
          <MyWorkCard
            key={`${item.kind}-${item.id}`}
            item={item}
            priority={index < 4}
            isLcpCandidate={index === 0}
          />
        ))}
      </div>
    </div>
  );
}

type MyWorkCardProps = {
  item: MyWorkItem;
  priority: boolean;
  isLcpCandidate: boolean;
};

/** 발행작은 홈·프로필과 같은 상세 모달로, 초안은 이어 쓰던 빌더로 간다. 초안이 `<Link>`가 아닌 이유는
 * 한 그리드 안에서 발행작 카드가 라우터를 우회하는 모달(`useContentDetailModal`)이라 링크가 될 수 없고,
 * 카드 안에 다른 동작을 넣을 자리(US-010의 ⋯ 메뉴)가 `role="button"` 패턴을 요구하기 때문이다. */
function MyWorkCard({ item, priority, isLcpCandidate }: MyWorkCardProps) {
  const navigate = useNavigate();
  const { open } = useContentDetailModal();

  return (
    <ContentCard
      thumbnailUrl={item.thumbnailUrl}
      // 초안은 이름이 비어 있는 게 정상 상태다 — US-007의 지연 생성은 사용자가 이름을 넣기 전에도 초안을
      // 만든다. 폴백을 공용 `ContentCard`가 아니라 여기 두는 이유: 홈·즐겨찾기·프로필에는 이름 없는
      // 발행작이 올 수 없어서, 공용 쪽에 넣으면 그쪽의 진짜 결함을 조용히 가리게 된다.
      title={item.kind === "draft" ? item.name || "제목 없는 초안" : item.name}
      metrics={
        item.kind === "published"
          ? { viewCount: item.viewCount, chatCount: item.chatCount, likeCount: item.likeCount }
          : undefined
      }
      // 초안에만 수정일을 단다 — 발행작의 `updatedAt`은 마지막 **발행** 시각이라(확정 결정 1)
      // 같은 "수정" 라벨을 붙이면 거짓말이 된다.
      metaLabel={item.kind === "draft" ? `${formatMyWorkUpdatedAt(item.updatedAt)} 수정` : undefined}
      tags={toTags(item)}
      priority={priority}
      isLcpCandidate={isLcpCandidate}
      onClick={() => {
        if (item.kind === "published") {
          open(item.type, item.id);
          return;
        }
        void navigate({ to: "/builder/$type/$draftId", params: { type: item.type, draftId: item.id } });
      }}
    />
  );
}

function toTags(item: MyWorkItem): ContentCardTag[] {
  // 초안에는 공개범위가 없다 — 배지는 "미등록" 하나뿐이다(확정 결정 6).
  return item.kind === "published" ? [item.type, item.visibility] : [item.type, "unpublished"];
}

/** 실제 카드 구조(썸네일 웰 + 제목 + 한 줄 + 배지)를 그대로 흉내 낸다 — `aspect-[3/4]` 한 장짜리
 * 스켈레톤은 390px에서 실제 카드보다 45.5px 짧아 목록이 도착할 때 2행이 46px, 3행이 91px씩 밀렸다(실측).
 *
 * `role="status"`가 있어야 `aria-label`이 읽힌다 — 암묵 role(generic)에 붙인 `aria-label`은 ARIA 1.2가
 * 금지하는 조합이라 스크린리더가 대개 무시한다(a11y 트리 실측). */
function MyWorksSkeleton() {
  return (
    <div
      role="status"
      aria-busy
      aria-label="내 작품 목록 불러오는 중"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
    >
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div
          key={key}
          className="flex flex-col gap-3 rounded-xl border border-border bg-background p-3 motion-safe:animate-pulse"
        >
          <div className="aspect-square rounded-lg bg-muted" />
          <div className="flex flex-col gap-1.5">
            {/* 20 / 16 / 22.5px는 실제 카드의 제목(text-sm) · 한 줄(text-xs) · 배지 행 높이다. */}
            <div className="h-5 w-3/4 rounded bg-muted" />
            <div className="h-4 w-1/2 rounded bg-muted" />
            <div className="h-[22px] w-2/3 rounded-full bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 목록 일부만 실패했을 때 목록 **위에** 얹는 한 줄 알림. 아래에 볼 것이 남아 있으므로 자리를 적게 쓴다. */
function MyWorksErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3">
      <p className="text-sm text-destructive">{message}</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  );
}

/** 셋 다 실패해 목록이 통째로 없을 때. 같은 "보여줄 게 없음" 상황인 빈 상태(`ContentListEmptyState`)와
 * 같은 dashed 패널 셸을 써서 한 화면에 빈 상태 어휘가 둘이 되지 않게 한다. */
function MyWorksFullErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-16 text-center"
    >
      <p className="text-sm text-destructive">목록을 불러오지 못했어요.</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  );
}
