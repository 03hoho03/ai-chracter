import { useState } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";
import { BookOpen, Heart, ImageOff, MessageCircle, UserRound } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import {
  canViewDetailPage,
  contentKeys,
  toContentAccessStatus,
  useContentDetailQuery,
  useToggleLikeMutation,
  type ContentType,
} from "../../../entities/content";
import { contentDetailModalAtom } from "../../../shared/model/content-detail-modal";
import { CharacterPlayButton } from "./CharacterPlayButton";
import { ContentUnavailableState } from "./ContentUnavailableState";
import { StoryDetailBody } from "./StoryDetailBody";

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

// techspec-overview.md §11 — 좋아요 토글은 연타 방지를 위해 네트워크 호출만 디바운스하고,
// 화면 표시는 desiredLiked로 매 클릭마다 즉시 반영한다.
const LIKE_SYNC_DEBOUNCE_MS = 400;

function ContentDetailSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-1">
      <div className="aspect-video w-full animate-pulse rounded-lg bg-muted" />
      <div className="h-6 w-2/3 animate-pulse rounded bg-muted" />
      <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
      <div className="h-20 w-full animate-pulse rounded bg-muted" />
    </div>
  );
}

/** techspec-content-detail.md §1~2 — 모달/풀페이지 공용 상세 콘텐츠. 카드가 있는 모든 리스트
 * (홈, 프로필)는 이 컴포넌트를 직접 렌더링하지 않고 `useContentDetailModal().open()`만 호출한다. */
export function ContentDetailView({ id }: { id: string }) {
  const detailQuery = useContentDetailQuery(id);
  const setModalState = useSetAtom(contentDetailModalAtom);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toggleLike = useToggleLikeMutation(id);
  const [desiredLiked, setDesiredLiked] = useState<boolean | undefined>(undefined);
  const content = detailQuery.data;

  useDebounce(
    () => {
      if (content === undefined || desiredLiked === undefined || desiredLiked === content.isLiked) return;
      const syncingLiked = desiredLiked;
      toggleLike.mutate(syncingLiked, {
        onError: (error) => {
          toast.error(
            error.status === 401 ? "로그인 후 좋아요를 남길 수 있어요." : "좋아요 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        },
        onSettled: () => {
          // 정산되는 사이 다시 클릭해 desiredLiked가 이미 다른 값으로 바뀌었다면(연타) 그 새 의도를 덮어쓰지 않는다.
          setDesiredLiked((current) => (current === syncingLiked ? undefined : current));
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
        },
      });
    },
    LIKE_SYNC_DEBOUNCE_MS,
    [desiredLiked],
  );

  if (detailQuery.isPending) return <ContentDetailSkeleton />;

  if (detailQuery.isError) {
    return (
      <p className="p-6 text-center text-sm text-destructive">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (content === undefined) return null;

  const access = toContentAccessStatus(content.accessStatus);

  if (!canViewDetailPage(access, content.isOwner)) {
    return <ContentUnavailableState access={access} />;
  }

  const isLiked = desiredLiked ?? content.isLiked;
  const likeCount = content.likeCount + (isLiked === content.isLiked ? 0 : isLiked ? 1 : -1);

  return (
    <article className="flex flex-col gap-5 p-1">
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-muted">
        {content.thumbnailUrl ? (
          <img src={content.thumbnailUrl} alt="" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className="inline-flex w-fit items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
          {content.type === "character" ? (
            <UserRound aria-hidden className="size-3.5" />
          ) : (
            <BookOpen aria-hidden className="size-3.5" />
          )}
          {TYPE_LABEL[content.type]}
        </span>

        <h1 className="text-xl font-bold tracking-tight text-foreground">{content.name}</h1>

        <Link
          to="/profile/$userId"
          params={{ userId: content.creatorUserId }}
          onClick={() => setModalState(null)}
          className="w-fit text-sm text-muted-foreground hover:underline"
        >
          {content.creatorNickname}
        </Link>

        <p className="text-xs text-muted-foreground">{content.genreName}</p>

        {content.hashtags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {content.hashtags.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => {
                  setModalState(null);
                  // techspec-home-discovery.md §2 — 해시태그 클릭 시 홈으로 이동해 해당 해시태그로 필터링한다.
                  void navigate({ to: "/", search: { hashtag: tag } });
                }}
                className="text-xs text-muted-foreground hover:underline"
              >
                #{tag}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <MessageCircle aria-hidden className="size-4" />
          {content.chatCount.toLocaleString()}
        </span>

        <button
          type="button"
          aria-pressed={isLiked}
          onClick={() => setDesiredLiked((current) => !(current ?? content.isLiked))}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md transition-colors hover:text-foreground",
            isLiked && "text-primary hover:text-primary",
          )}
        >
          <Heart aria-hidden className={cn("size-4", isLiked && "fill-primary")} />
          {likeCount.toLocaleString()}
          <span className="sr-only">{isLiked ? "좋아요 취소" : "좋아요"}</span>
        </button>
      </div>

      <p className="text-sm font-medium text-foreground">{content.oneLiner}</p>

      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{content.detailDescription}</p>

      {content.type === "story" ? (
        <StoryDetailBody contentId={content.id} startingSetups={content.startingSetups ?? []} />
      ) : (
        <CharacterPlayButton contentId={content.id} />
      )}
    </article>
  );
}
