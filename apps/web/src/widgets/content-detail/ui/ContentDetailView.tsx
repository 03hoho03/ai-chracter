import { useEffect, useRef, useState } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";
import { BookOpen, ChevronRight, Heart, History, ImageOff, MessageCircle, Star, UserRound } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import {
  canViewDetailPage,
  contentDetailModalAtom,
  contentKeys,
  favoriteKeys,
  toContentAccessStatus,
  toThumbnailAspect,
  toThumbnailAspectClass,
  useContentDetailQuery,
  useToggleFavoriteMutation,
  useToggleLikeMutation,
  type ContentType,
  type ThumbnailAspect,
} from "@/entities/content";

import { CharacterChatHistoryLink, CharacterPlayBar } from "./CharacterPlayBar";
import { ContentActionsMenu } from "./ContentActionsMenu";
import { ContentUnavailableState } from "./ContentUnavailableState";
import { StoryDetailBody, StoryPlayBar } from "./StoryDetailBody";
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

// image-crop-goal-prompt.md IC-11 — 캐릭터(1열)는 모바일에서 `w-full` 그대로, 데스크톱은 높이 예산
// 60dvh가 단일 소스(1:1이라 폭 상한도 같은 값). `max-height`가 아니라 `max-width`로 거는 이유:
// `aspect-ratio` + `w-full` 상태에서 `max-height`는 폭을 줄이지 않아 비율이 깨지고 `object-cover`가
// 다시 자른다.
const CHARACTER_HERO_WIDTH_CLASS = "sm:max-w-[60dvh]";

// image-crop-goal-prompt.md IC-11 — 스토리(2열)는 우측 열과 나란히 두므로 높이가 아니라 고정 폭이
// 예산이다: `sm:w-64`(256px) × `aspect-story`(2:3) = 256×384. 예전 높이 캡(`sm:max-w-[40dvh]`)은 폭이
// 이미 고정인 2열 레이아웃에서는 의미가 없어져 뺐다.
const STORY_HERO_WIDTH_CLASS = "sm:w-64 sm:shrink-0";

// image-crop-goal-prompt.md IC-11 — 실제 hero와 스켈레톤이 이 함수 하나를 같이 써야 도착 시 폭이 안
// 밀린다(스켈레톤이 실제와 다른 모양이면 도착 순간 화면이 밀린 전례, card-grid-goal-prompt.md F-1).
function toHeroClassName(type: ContentType, aspect: ThumbnailAspect, visualClass: string): string {
  if (type === "character") {
    return cn("mx-auto w-full", visualClass, toThumbnailAspectClass(aspect), CHARACTER_HERO_WIDTH_CLASS);
  }
  return cn("w-full", visualClass, toThumbnailAspectClass(aspect), STORY_HERO_WIDTH_CLASS);
}

// techspec-overview.md §11 — 좋아요/즐겨찾기 토글은 연타 방지를 위해 네트워크 호출만 디바운스하고,
// 화면 표시는 isLikeDesired/isFavoriteDesired로 매 클릭마다 즉시 반영한다.
const TOGGLE_SYNC_DEBOUNCE_MS = 400;

type ContentDetailViewProps = {
  id: string;
  /** image-crop-goal-prompt.md IC-11 — content 도착 전(스켈레톤)에는 실제 타입을 모르므로 호출부가
   * 힌트로 넘긴다. 값이 틀려도 스켈레톤 비율만 잠깐 틀리고 도착 시 실제 타입으로 뛴다 — 조회·표시
   * 로직에는 절대 쓰지 않는다(아래에서는 전부 `content.type`을 쓴다). */
  type: ContentType;
  variant: "modal" | "page";
};

/** techspec-content-detail.md §1~2 — 모달/풀페이지 공용 상세 콘텐츠. 카드가 있는 모든 리스트
 * (홈, 프로필)는 이 컴포넌트를 직접 렌더링하지 않고 `useContentDetailModal().open()`만 호출한다.
 * `variant`는 design-system-progress.md P-5(D-7/D-11) — 플레이 CTA를 하단에 고정하는 방식이
 * 모달(카드 안 flex)과 풀페이지(lg 미만 fixed)에서 구조 자체가 달라 호출부가 명시한다. */
export function ContentDetailView({ id, type, variant }: ContentDetailViewProps) {
  const detailQuery = useContentDetailQuery(id);
  const setModalState = useSetAtom(contentDetailModalAtom);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toggleLike = useToggleLikeMutation(id);
  const toggleFavorite = useToggleFavoriteMutation(id);
  const [isLikeDesired, setIsLikeDesired] = useState<boolean | undefined>(undefined);
  const [isFavoriteDesired, setIsFavoriteDesired] = useState<boolean | undefined>(undefined);
  const [isVersionHistoryOpen, setIsVersionHistoryOpen] = useState(false);
  // 스토리 전용 — 시작설정 선택. `StoryDetailBody`(스크롤 영역의 선택기)와 `StoryPlayBar`(하단
  // 고정 바)가 형제로 갈라지면서(P-5) 상태를 여기서 들고 있어야 서로 공유할 수 있다. 캐릭터는 쓰지
  // 않지만 다른 optimistic override들과 같은 이유로 무조건 호출한다(hooks 규칙).
  const [selectedSetupIdOverride, setSelectedSetupIdOverride] = useState<string | undefined>(undefined);
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
      if (content === undefined || isLikeDesired === undefined || isLikeDesired === content.isLiked) return;
      const isNextLiked = isLikeDesired;
      toggleLike.mutate(isNextLiked, {
        onError: (error) => {
          toast.error(
            error.status === 401 ? "로그인 후 좋아요를 남길 수 있어요." : "좋아요 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        },
        onSettled: () => {
          // 정산되는 사이 다시 클릭해 isLikeDesired가 이미 다른 값으로 바뀌었다면(연타) 그 새 의도를 덮어쓰지 않는다.
          setIsLikeDesired((current) => (current === isNextLiked ? undefined : current));
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
        },
      });
    },
    TOGGLE_SYNC_DEBOUNCE_MS,
    [isLikeDesired],
  );

  useDebounce(
    () => {
      if (
        content === undefined ||
        isFavoriteDesired === undefined ||
        isFavoriteDesired === content.isFavorited
      )
        return;
      const isNextFavorited = isFavoriteDesired;
      toggleFavorite.mutate(isNextFavorited, {
        onError: (error) => {
          toast.error(
            error.status === 401
              ? "로그인 후 즐겨찾기에 담을 수 있어요."
              : "즐겨찾기 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        },
        onSettled: () => {
          setIsFavoriteDesired((current) => (current === isNextFavorited ? undefined : current));
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
          // `favoriteKeys.list(type)`이 타입별로 캐시를 가른다(card-grid-techspec.md T-1) — 접두사로
          // 두 타입 모두 무효화한다. 한쪽만 지우면 반대 타입 즐겨찾기 목록이 stale로 남는다.
          void queryClient.invalidateQueries({ queryKey: favoriteKeys.all });
        },
      });
    },
    TOGGLE_SYNC_DEBOUNCE_MS,
    [isFavoriteDesired],
  );

  if (detailQuery.isPending) return <ContentDetailSkeleton type={type} />;

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

  const isLiked = isLikeDesired ?? content.isLiked;
  const likeCount = content.likeCount + optimisticDelta(isLiked, content.isLiked);
  const isFavorited = isFavoriteDesired ?? content.isFavorited;
  const selectedSetupId = selectedSetupIdOverride ?? content.startingSetups?.[0]?.id;

  const footer =
    content.type === "story" ? (
      <StoryPlayBar
        contentId={content.id}
        startingSetups={content.startingSetups ?? []}
        selectedSetupId={selectedSetupId}
        onRestoreSetup={setSelectedSetupIdOverride}
      />
    ) : (
      <CharacterPlayBar contentId={content.id} />
    );

  // image-crop-goal-prompt.md IC-11 — hero 비율은 카드 그리드와 같은 도메인→표현 매핑
  // (`toThumbnailAspect`)을 재사용한다: 캐릭터 1:1, 스토리 2:3.
  const heroAspect = toThumbnailAspect(content.type);

  const body = (
    <article className="flex flex-col gap-5 p-1">
      {/* image-crop-goal-prompt.md IC-11 — 스토리는 ≥sm에서 hero+메타를 가로 2열로 두고(사용자 피드백
          "메타데이터가 이미지 오른쪽"), 캐릭터는 지금처럼 1열을 유지한다. */}
      <div
        className={cn("flex flex-col gap-5", content.type === "story" && "sm:flex-row sm:items-start sm:gap-6")}
      >
        <div className={toHeroClassName(content.type, heroAspect, "overflow-hidden rounded-lg bg-muted")}>
          {/* US-013 — 상세(페이지·모달 공용)의 첫 화면 주인공 이미지라 모달 그리드와 같은 이유로 lazy 제외. */}
          {content.thumbnailUrl ? (
            <img src={content.thumbnailUrl} alt="" decoding="async" className="size-full object-cover" />
          ) : (
            <div className="flex size-full items-center justify-center text-muted-foreground">
              <ImageOff aria-hidden />
            </div>
          )}
        </div>

        {/* min-w-0 — flex 자식의 기본 min-width:auto 때문에 긴 제목·해시태그가 열을 밀어내는 것을 막는다. */}
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="inline-flex w-fit items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-badge font-medium text-secondary-foreground">
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
              onClick={() => setModalState(undefined)}
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
                      setModalState(undefined);
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
              onClick={() => setIsLikeDesired((current) => !(current ?? content.isLiked))}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md motion-safe:transition-colors hover:text-foreground",
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
              onClick={() => setIsFavoriteDesired((current) => !(current ?? content.isFavorited))}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md motion-safe:transition-colors hover:text-foreground",
                isFavorited && "text-primary hover:text-primary",
              )}
            >
              <Star aria-hidden className={cn("size-4", isFavorited && "fill-primary")} />
              <span className="sr-only">{isFavorited ? "즐겨찾기 해제" : "즐겨찾기"}</span>
            </button>

          </div>

          <p className="text-sm font-medium text-foreground">{content.oneLiner}</p>
        </div>
      </div>

      {/* image-crop-goal-prompt.md IC-11 — 우측 열 폭이 ~350px인데 본문이 `text-sm`이라 한 줄에 21자밖에
          안 들어간다. 긴 산문은 2열에 넣지 않고 전폭으로 둔다. */}
      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{content.detailDescription}</p>

      {content.type === "story" && (
        <StoryDetailBody
          startingSetups={content.startingSetups ?? []}
          selectedSetupId={selectedSetupId}
          onSelectedSetupIdChange={setSelectedSetupIdOverride}
        />
      )}
      {content.type === "character" && <CharacterChatHistoryLink contentId={content.id} />}

      {/* 업데이트 이력은 대화수·좋아요 같은 **지표가 아니다** — 통계 줄에 섞여 있어서 2열로 좁아진
          우측 열에서 자리를 다퉜다(2026-09-15 실사용 제보). 참고 정보라 플레이로 가는 길(시작설정
          선택)을 끊지 않게 맨 아래에 둔다.
          hover 표면이 `bg-muted`가 아닌 이유: `--muted`와 `--popover`가 다크 0.210 / 라이트 0.970으로
          **값이 같아** 모달 안에서 hover가 통째로 사라진다(같은 함정을 Slider 트랙에서 겪었다).
          `secondary`는 페이지 배경·모달 표면 양쪽에서 살아남는다. */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">업데이트</h2>
        <button
          type="button"
          onClick={() => setIsVersionHistoryOpen(true)}
          className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-left text-sm text-muted-foreground motion-safe:transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <History aria-hidden className="size-4 shrink-0" />
          <span className="min-w-0 flex-1 break-keep">
            최근 업데이트 {UPDATED_AT_FORMATTER.format(new Date(content.updatedAt))} · v{content.versionNumber}
          </span>
          <ChevronRight aria-hidden className="size-4 shrink-0" />
        </button>
      </section>

      <VersionHistoryModal
        contentId={content.id}
        open={isVersionHistoryOpen}
        onOpenChange={setIsVersionHistoryOpen}
      />
    </article>
  );

  // design-system-progress.md P-5(D-7/D-11) — 플레이 CTA를 스크롤 영역 밖으로 뽑아 하단에 고정한다.
  if (variant === "modal") {
    // 모달은 폭과 무관하게 전 폭에서 고정한다(분기 없음) — `DialogContent`가 이 컴포넌트의 호출부에서
    // 이미 `flex flex-col`이라, 여기서는 그 두 flex 아이템만 내놓는다. 카드 안 flex 배치라 겹칠
    // 다른 fixed/absolute 레이어가 없으므로 z-index 경쟁이 없다.
    return (
      <>
        <div className="min-h-0 flex-1 overflow-y-auto">{body}</div>
        <div className="-mx-4 -mb-4 shrink-0 rounded-b-xl border-t border-border bg-popover p-4 pb-4-safe">
          {footer}
        </div>
      </>
    );
  }

  return (
    <>
      {body}
      {/* 풀페이지는 자연 문서 스크롤이라 모달과 같은 flex 트릭을 못 쓴다(P-0-3-⑤) — `lg` 미만에서만
          뷰포트 기준 `fixed` 바로, `lg` 이상은 지금처럼 본문 안 인라인으로 되돌아간다(넓은 화면의
          전폭 고정 바는 DESIGN.md가 경계하는 "상시 크롬"에 가깝다는 판단, 확정 결정).
          z-40: 헤더(`z-30`, sticky)와는 화면 위/아래로 겹칠 일이 없어 순서가 기능에 영향을 주지
          않지만, 이 화면에 뜨는 Dialog/Sheet(`z-50`)는 항상 이 바 위를 덮어야 하므로 그 아래로 둔다. */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background p-4 pb-4-safe lg:static lg:inset-auto lg:z-auto lg:mt-5 lg:border-t-0 lg:bg-transparent lg:p-0 lg:pb-0">
        {footer}
      </div>
    </>
  );
}

// image-crop-goal-prompt.md IC-11 — content 도착 전이라 `content.type`을 못 읽으므로 호출부가 넘긴
// `type`(모달: 상태에 이미 있음, 페이지: URL 세그먼트)으로 같은 비율을 흉내 낸다. 어긋나면 도착 시
// 화면이 밀린다(card-grid-goal-prompt.md F-1 전례).
function ContentDetailSkeleton({ type }: { type: ContentType }) {
  const heroAspect = toThumbnailAspect(type);
  return (
    <div className="flex flex-col gap-4 p-1">
      {/* image-crop-goal-prompt.md IC-11 — 실제 본문과 같은 2열 분기(스토리만 ≥sm에서 flex-row)를
          흉내 내지 않으면 도착 시 화면이 밀린다(card-grid-goal-prompt.md F-1 전례). */}
      <div className={cn("flex flex-col gap-4", type === "story" && "sm:flex-row sm:items-start sm:gap-6")}>
        <div className={toHeroClassName(type, heroAspect, "animate-pulse rounded-lg bg-muted")} />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="h-6 w-2/3 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
        </div>
      </div>
      <div className="h-20 w-full animate-pulse rounded bg-muted" />
    </div>
  );
}

/** 낙관적 토글이 서버 값과 갈릴 때만 카운트를 ±1 한다 — 서버 카운트를 다시 받기 전까지 화면만
 * 앞서간다. 중첩 삼항으로 쓰면 "같으면 0"과 "다르면 방향"이라는 두 질문이 한 줄에 겹친다(COMP-04). */
function optimisticDelta(optimistic: boolean, server: boolean): number {
  if (optimistic === server) return 0;
  return optimistic ? 1 : -1;
}
