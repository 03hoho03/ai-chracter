import { useEffect, useRef, useState } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";
import { BookOpen, Heart, History, ImageOff, MessageCircle, Star, UserRound } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import {
  canViewDetailPage,
  contentKeys,
  favoriteKeys,
  toContentAccessStatus,
  useContentDetailQuery,
  useToggleFavoriteMutation,
  useToggleLikeMutation,
  type ContentType,
} from "@/entities/content";
import { contentDetailModalAtom } from "@/shared/model/content-detail-modal";

import { CharacterPlayButton } from "./CharacterPlayButton";
import { ContentActionsMenu } from "./ContentActionsMenu";
import { ContentUnavailableState } from "./ContentUnavailableState";
import { StoryDetailBody } from "./StoryDetailBody";
import { VersionHistoryModal } from "./VersionHistoryModal";

const UPDATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

// techspec-overview.md §11 — 좋아요/즐겨찾기 토글은 연타 방지를 위해 네트워크 호출만 디바운스하고,
// 화면 표시는 desiredLiked/desiredFavorited로 매 클릭마다 즉시 반영한다.
const TOGGLE_SYNC_DEBOUNCE_MS = 400;

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
  const toggleFavorite = useToggleFavoriteMutation(id);
  const [desiredLiked, setDesiredLiked] = useState<boolean | undefined>(undefined);
  const [desiredFavorited, setDesiredFavorited] = useState<boolean | undefined>(undefined);
  const [isVersionHistoryOpen, setIsVersionHistoryOpen] = useState(false);
  const content = detailQuery.data;

  // 상세 GET이 백그라운드로 조회수를 올리므로 홈 목록을 무효화해야 한다 — 모달 경로는 홈 리스트가
  // 언마운트되지 않아 이것 없이는 닫아도 카드 숫자가 갱신되지 않는다.
  // dataUpdatedAt이 트리거인 이유: 상세 응답에 viewCount가 없어 페이로드가 동일하면 structural
  // sharing으로 data 참조가 안 바뀌지만, dataUpdatedAt은 fetch가 해석될 때마다 바뀐다.
  // ref 가드는 마운트 시점 값(재열람이면 캐시된 이전 타임스탬프)을 무시하기 위한 것 — staleTime 0이라
  // 마운트 리페치가 곧 새 타임스탬프를 만든다.
  const detailUpdatedAt = detailQuery.dataUpdatedAt;
  const lastSeenUpdatedAtRef = useRef(detailUpdatedAt);
  const hasCountedViewRef = useRef(false);
  useEffect(() => {
    if (detailUpdatedAt === lastSeenUpdatedAtRef.current) return;
    lastSeenUpdatedAtRef.current = detailUpdatedAt;
    hasCountedViewRef.current = true;
  }, [detailUpdatedAt]);

  // 무효화는 응답 해석 시점이 아니라 **언마운트(모달 닫힘/상세 이탈) 시점**에 한 번만 한다. BE의
  // 증가는 응답을 보낸 뒤 도는 BackgroundTasks라, 해석 즉시 무효화하면 그 백그라운드 증가와 목록
  // 리페치가 경쟁한다 — localhost에선 BE가 이기지만 Cloud Run+Neon+Upstash처럼 Redis/DB가
  // 네트워크 건너편이면 리페치가 먼저 도착해 옛 숫자가 그대로 남을 수 있다. 사용자가 상세를 보는
  // 체류 시간을 통째로 여유로 쓰면 그 창이 사실상 닫힌다. 덤으로 모달 뒤에 가려 안 보이는 리스트를
  // 여는 동안 리페치하지 않게 되어, 스크롤이 깊을수록 커지던 전 페이지 리페치도 한 번으로 줄어든다.
  useEffect(
    () => () => {
      if (!hasCountedViewRef.current) return;
      void queryClient.invalidateQueries({ queryKey: contentKeys.browseAll() });
    },
    [queryClient],
  );

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
    TOGGLE_SYNC_DEBOUNCE_MS,
    [desiredLiked],
  );

  useDebounce(
    () => {
      if (
        content === undefined ||
        desiredFavorited === undefined ||
        desiredFavorited === content.isFavorited
      )
        return;
      const syncingFavorited = desiredFavorited;
      toggleFavorite.mutate(syncingFavorited, {
        onError: (error) => {
          toast.error(
            error.status === 401
              ? "로그인 후 즐겨찾기에 담을 수 있어요."
              : "즐겨찾기 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        },
        onSettled: () => {
          setDesiredFavorited((current) => (current === syncingFavorited ? undefined : current));
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
          void queryClient.invalidateQueries({ queryKey: favoriteKeys.list() });
        },
      });
    },
    TOGGLE_SYNC_DEBOUNCE_MS,
    [desiredFavorited],
  );

  if (detailQuery.isPending) return <ContentDetailSkeleton />;

  if (detailQuery.isError) {
    return (
      <p className="p-6 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (content === undefined) return null;

  const access = toContentAccessStatus(content.accessStatus);

  // `kind` 검사는 `canViewDetailPage`가 이미 포함하지만(restricted/deleted면 false) 그 함수는 타입
  // 술어가 아니다 — 아래에서 `access.visibility`(전환 메뉴의 "현재 값")를 쓰려면 여기서 좁혀야 한다.
  if (access.kind !== "accessible" || !canViewDetailPage(access, content.isOwner)) {
    return <ContentUnavailableState access={access} />;
  }

  const isLiked = desiredLiked ?? content.isLiked;
  const likeCount = content.likeCount + optimisticDelta(isLiked, content.isLiked);
  const isFavorited = desiredFavorited ?? content.isFavorited;

  return (
    <article className="flex flex-col gap-5 p-1">
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-muted">
        {/* US-013 — 상세(페이지·모달 공용)의 첫 화면 주인공 이미지라 모달 그리드와 같은 이유로 lazy 제외. */}
        {content.thumbnailUrl ? (
          <img src={content.thumbnailUrl} alt="" decoding="async" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="inline-flex w-fit items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
            {content.type === "character" ? (
              <UserRound aria-hidden className="size-3.5" />
            ) : (
              <BookOpen aria-hidden className="size-3.5" />
            )}
            {TYPE_LABEL[content.type]}
          </span>

          {/* `access.kind === "accessible"`로 이미 좁혀진 자리다(위 early return) — 그래서 여기 오는
              콘텐츠의 모더레이션 상태는 `normal`이다. 상세 응답은 `moderationStatus`를 따로 내려주지 않고
              `accessStatus`로 접어 주므로 이 좁힘이 그 값의 유일한 출처다. */}
          <ContentActionsMenu
            contentId={content.id}
            creatorUserId={content.creatorUserId}
            isOwner={content.isOwner}
            visibility={access.visibility}
            moderationStatus="normal"
          />
        </div>

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

        <button
          type="button"
          aria-pressed={isFavorited}
          onClick={() => setDesiredFavorited((current) => !(current ?? content.isFavorited))}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md transition-colors hover:text-foreground",
            isFavorited && "text-primary hover:text-primary",
          )}
        >
          <Star aria-hidden className={cn("size-4", isFavorited && "fill-primary")} />
          <span className="sr-only">{isFavorited ? "즐겨찾기 해제" : "즐겨찾기"}</span>
        </button>

        <button
          type="button"
          onClick={() => setIsVersionHistoryOpen(true)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md transition-colors hover:text-foreground"
        >
          <History aria-hidden className="size-4" />
          최근 업데이트 {UPDATED_AT_FORMATTER.format(new Date(content.updatedAt))} · v{content.versionNumber}
        </button>
      </div>

      <p className="text-sm font-medium text-foreground">{content.oneLiner}</p>

      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{content.detailDescription}</p>

      {content.type === "story" ? (
        <StoryDetailBody contentId={content.id} startingSetups={content.startingSetups ?? []} />
      ) : (
        <CharacterPlayButton contentId={content.id} />
      )}

      <VersionHistoryModal
        contentId={content.id}
        open={isVersionHistoryOpen}
        onOpenChange={setIsVersionHistoryOpen}
      />
    </article>
  );
}

/** 낙관적 토글이 서버 값과 갈릴 때만 카운트를 ±1 한다 — 서버 카운트를 다시 받기 전까지 화면만
 * 앞서간다. 중첩 삼항으로 쓰면 "같으면 0"과 "다르면 방향"이라는 두 질문이 한 줄에 겹친다(COMP-04). */
function optimisticDelta(optimistic: boolean, server: boolean): number {
  if (optimistic === server) return 0;
  return optimistic ? 1 : -1;
}
