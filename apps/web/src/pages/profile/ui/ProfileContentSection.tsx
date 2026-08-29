import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";

import {
  ContentCard,
  ContentCardActionMenu,
  ContentListLoadMore,
  isVisibilityFilter,
  toContentStatusTags,
  useProfileContentListQuery,
  VISIBILITY_FILTER_OPTIONS,
  type ContentCardTag,
  type ContentSummary,
  type ContentType,
  type VisibilityFilter,
} from "@/entities/content";
import { VisibilityTransitionMenuItems } from "@/features/change-content-visibility";
import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

type ProfileContentSectionProps = {
  userId: string;
  isOwner: boolean;
  contentType: ContentType;
  onContentTypeChange: (type: ContentType) => void;
};

/** techspec-global-nav-profile.md §3.2 — [스토리]/[캐릭터] 유형 토글(부모가 URL search param과
 * 동기화)과, 본인 조회일 때만 노출되는 공개여부 필터(로컬 상태, 기본값 "전체")를 함께 렌더링한다. */
export function ProfileContentSection({
  userId,
  isOwner,
  contentType,
  onContentTypeChange,
}: ProfileContentSectionProps) {
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>("all");
  const gridRef = useRef<HTMLDivElement>(null);

  const contentListQuery = useProfileContentListQuery({
    userId,
    type: contentType,
    visibilityFilter: isOwner ? visibilityFilter : undefined,
  });

  // 유형 토글과 공개여부 필터는 둘 다 쿼리키에 들어가 있어(`contentKeys.list`) 바뀌는 순간 **새 쿼리**가
  // 된다 — 목록도 커서도 첫 페이지로 돌아가므로 이전 필터의 커서가 남아 섞일 자리가 없다(US-009).
  const items = contentListQuery.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup
          type="single"
          variant="outline"
          value={contentType}
          onValueChange={(value) => {
            if (value === "character" || value === "story") onContentTypeChange(value);
          }}
          aria-label="작품 유형 전환"
        >
          <ToggleGroupItem value="story" aria-label="스토리">
            스토리
          </ToggleGroupItem>
          <ToggleGroupItem value="character" aria-label="캐릭터">
            캐릭터
          </ToggleGroupItem>
        </ToggleGroup>

        {isOwner && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={visibilityFilter}
            onValueChange={(value) => {
              if (isVisibilityFilter(value)) setVisibilityFilter(value);
            }}
            aria-label="공개여부 필터"
          >
            {VISIBILITY_FILTER_OPTIONS.map((option) => (
              <ToggleGroupItem key={option.value} value={option.value}>
                {option.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>

      {/* 네 상태가 배타적이지 않아 순서를 명시적으로 만든다(COMP-04) — `isError`와 `data`는 **동시에
          참일 수 있다**(성공 후 재조회 실패 시 `data`가 이전 값을 유지한 채 `isError`가 붙는다).
          예전엔 그래서 에러 문단과 목록이 함께 렌더됐다.

          `isPending && failureCount === 0`인 이유는 `/my`(MyWorksPage)와 같다: 재시도 백오프 중에도
          `isPending`이라, 그것만 보면 이미 도착한 목록이 최대 7초(3회 1s→2s→4s) 스켈레톤에 갇힌다. */}
      {contentListQuery.isPending && contentListQuery.failureCount === 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((key) => (
            <div key={key} className="aspect-[3/4] animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      )}

      {/* 보여줄 목록이 없을 때만 전면 에러다 — 있으면 아래 배너로 알리고 목록을 살린다(/my 선례). */}
      {contentListQuery.isError && items.length === 0 && (
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {contentListQuery.isError && items.length > 0 && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-destructive-text">
            새로고침에 실패했어요. 보이는 목록이 최신이 아닐 수 있어요.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => void contentListQuery.refetch()}>
            다시 시도
          </Button>
        </div>
      )}

      {!contentListQuery.isPending && !contentListQuery.isError && items.length === 0 && (
        <p className="text-sm text-muted-foreground">아직 {TYPE_LABEL[contentType]} 작품이 없어요.</p>
      )}

      {items.length > 0 && (
        // `tabIndex={-1}`은 Tab 순서에 넣지 않으면서 프로그램 포커스만 받게 한다 — "더 보기"가
        // 마지막 페이지에서 사라질 때 포커스를 여기로 넘긴다(A-2).
        <div
          ref={gridRef}
          tabIndex={-1}
          className="grid grid-cols-2 gap-3 outline-none sm:grid-cols-3 md:grid-cols-4"
        >
          {items.map((content, index) => (
            <ProfileContentCard
              key={content.id}
              content={content}
              isOwner={isOwner}
              ownerUserId={userId}
              priority={index < 4}
              isLcpCandidate={index === 0}
            />
          ))}
        </div>
      )}

      <ContentListLoadMore
        hasMore={contentListQuery.hasNextPage}
        isLoading={contentListQuery.isFetchingNextPage}
        onLoadMore={() => {
          if (contentListQuery.hasNextPage && !contentListQuery.isFetchingNextPage) {
            void contentListQuery.fetchNextPage();
          }
        }}
        onExhausted={() => gridRef.current?.focus()}
      />
    </section>
  );
}

type ProfileContentCardProps = {
  content: ContentSummary;
  isOwner: boolean;
  ownerUserId: string;
  /** US-013 — 공용 ContentCard와 같은 규칙. 그리드가 `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라
   * 첫 줄이 뷰포트에 따라 2/3/4장으로 갈리므로 호출부는 최대값 4를 기준으로 `index < 4`에 준다. */
  priority?: boolean;
  /** LCP 후보 1장(`index === 0`)에만 준다. */
  isLcpCandidate?: boolean;
};

/** 공용 `ContentCard`에 프로필 전용 배지·메뉴만 얹는 얇은 어댑터. 카드 자체(썸네일 웰·이미지 로딩 정책·
 * 클릭/키 영역)는 `/my`(US-008)와 공유한다. */
function ProfileContentCard({
  content,
  isOwner,
  ownerUserId,
  priority = false,
  isLcpCandidate = false,
}: ProfileContentCardProps) {
  const { open } = useContentDetailModal();

  // 상태 배지는 소유자에게만 보인다(DESIGN.md §Status badges). 조합 자체는 `/my`와 **같은 함수**가
  // 정한다 — 사본이 둘이면 두 화면이 같은 작품에 다른 말을 한다(US-008).
  const tags: ContentCardTag[] = [content.type];
  if (isOwner) tags.push(...toContentStatusTags(content));

  return (
    <ContentCard
      thumbnailUrl={content.thumbnailUrl}
      title={content.name}
      metrics={{ viewCount: content.viewCount }}
      tags={tags}
      actions={
        isOwner ? (
          <VisibilityMenu content={content} ownerUserId={ownerUserId} />
        ) : undefined
      }
      priority={priority}
      isLcpCandidate={isLcpCandidate}
      onClick={() => open(content.type, content.id)}
    />
  );
}

/* US-005 — 소유자만 보는 공개범위 전환 메뉴. 카드가 클릭 영역이라 지켜야 할 것(click·keydown 양쪽
   stopPropagation, hover 토큰, 메뉴 폭)은 전부 `ContentCardActionMenu`가 갖고 있다 — US-010이 `/my`에
   두 번째 "⋯"를 만들면서 같은 셸이 두 벌이 됐고, 그때 이미 두 곳의 `aria-label`이 갈려 있었다. */
function VisibilityMenu({ content, ownerUserId }: { content: ContentSummary; ownerUserId: string }) {
  return (
    <ContentCardActionMenu title={content.name}>
      <VisibilityTransitionMenuItems
        contentId={content.id}
        creatorUserId={ownerUserId}
        currentVisibility={content.visibility}
        moderationStatus={content.moderationStatus}
      />
    </ContentCardActionMenu>
  );
}
