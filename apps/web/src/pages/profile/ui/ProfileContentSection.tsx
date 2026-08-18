import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { BookOpen, ImageOff, UserRound } from "lucide-react";

import {
  resolveAccessStatus,
  useProfileContentListQuery,
  type ContentSummary,
  type ContentType,
  type VisibilityFilter,
} from "../../../entities/content";
import { MakeContentPrivateModal } from "../../../features/make-content-private";
import { useContentDetailModal } from "../../../shared/lib/content-detail-modal/useContentDetailModal";

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

const VISIBILITY_LABEL: Record<ContentSummary["visibility"], string> = {
  public: "공개",
  link: "링크공개",
  private: "비공개",
};

const VISIBILITY_FILTER_OPTIONS: { value: VisibilityFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "public", label: "공개" },
  { value: "link", label: "링크공개" },
  { value: "private", label: "비공개" },
];

function ContentTypeIcon({ type }: { type: ContentType }) {
  return type === "character" ? (
    <UserRound aria-hidden className="size-3.5" />
  ) : (
    <BookOpen aria-hidden className="size-3.5" />
  );
}

function ContentCard({
  content,
  isOwner,
  ownerUserId,
  priority = false,
  isLcpCandidate = false,
}: {
  content: ContentSummary;
  isOwner: boolean;
  ownerUserId: string;
  /** US-013 — entities의 공용 ContentCard와 같은 규칙. 그리드가
   * `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라 첫 줄이 뷰포트에 따라 2/3/4장으로 갈리므로
   * 호출부는 최대값 4를 기준으로 `index < 4`에 준다. */
  priority?: boolean;
  /** LCP 후보 1장(`index === 0`)에만 준다. */
  isLcpCandidate?: boolean;
}) {
  // techspec-content-versioning.md §1 — restricted 여부만 이 함수로 판정하고, 공개범위 태그는
  // content.visibility를 그대로 쓴다(restricted 케이스도 두 태그가 함께 노출돼야 하므로).
  const access = resolveAccessStatus(content.visibility, content.moderationStatus);
  const { open } = useContentDetailModal();
  // US-115(FR-67) — 완전 삭제 액션은 없고 비공개 전환만 허용되며, 이미 비공개인 항목엔 노출하지 않는다.
  const canMakePrivate = isOwner && content.visibility !== "private";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => open(content.type, content.id)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        open(content.type, content.id);
      }}
      className="flex w-full cursor-pointer flex-col gap-3 rounded-xl border border-border bg-card p-3 text-left transition-colors hover:bg-accent/50"
    >
      <div className="aspect-square overflow-hidden rounded-lg bg-muted">
        {content.thumbnailUrl ? (
          <img
            src={content.thumbnailUrl}
            alt=""
            loading={priority ? "eager" : "lazy"}
            fetchPriority={isLcpCandidate ? "high" : "auto"}
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="truncate text-sm font-semibold text-foreground">{content.name}</p>
        <p className="text-xs text-muted-foreground">조회수 {content.viewCount.toLocaleString()}</p>

        <div className="flex flex-wrap gap-1.5">
          <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
            <ContentTypeIcon type={content.type} />
            {TYPE_LABEL[content.type]}
          </span>

          {isOwner && (
            <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {VISIBILITY_LABEL[content.visibility]}
            </span>
          )}

          {isOwner && access.kind === "restricted" && (
            <span className="inline-flex items-center rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-medium text-destructive">
              이용제한
            </span>
          )}
        </div>

        {canMakePrivate && (
          <Button
            type="button"
            variant="outline"
            size="xs"
            className="w-fit"
            onClick={(event) => {
              event.stopPropagation();
              void MakeContentPrivateModal.call({ contentId: content.id, creatorUserId: ownerUserId });
            }}
          >
            비공개 전환
          </Button>
        )}
      </div>
    </div>
  );
}

/** techspec-global-nav-profile.md §3.2 — [스토리]/[캐릭터] 유형 토글(부모가 URL search param과
 * 동기화)과, 본인 조회일 때만 노출되는 공개여부 필터(로컬 상태, 기본값 "전체")를 함께 렌더링한다. */
export function ProfileContentSection({
  userId,
  isOwner,
  contentType,
  onContentTypeChange,
}: {
  userId: string;
  isOwner: boolean;
  contentType: ContentType;
  onContentTypeChange: (type: ContentType) => void;
}) {
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>("all");

  const contentListQuery = useProfileContentListQuery({
    userId,
    type: contentType,
    visibilityFilter: isOwner ? visibilityFilter : undefined,
  });

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
              if (value) setVisibilityFilter(value as VisibilityFilter);
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

      {contentListQuery.isPending && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((key) => (
            <div key={key} className="aspect-[3/4] animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      )}

      {contentListQuery.isError && (
        <p className="text-sm text-destructive">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {contentListQuery.data && contentListQuery.data.length === 0 && (
        <p className="text-sm text-muted-foreground">아직 {TYPE_LABEL[contentType]} 작품이 없어요.</p>
      )}

      {contentListQuery.data && contentListQuery.data.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {contentListQuery.data.map((content, index) => (
            <ContentCard
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
    </section>
  );
}
