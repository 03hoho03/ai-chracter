import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useSetAtom } from "jotai";
import {
  BookOpen,
  ChevronRight,
  Heart,
  History,
  ImageOff,
  MessageCircle,
  Star,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import {
  canViewDetailPage,
  contentDetailModalAtom,
  contentKeys,
  favoriteKeys,
  toContentAccessStatus,
  toHomeTypeParam,
  toThumbnailAspect,
  toThumbnailAspectClass,
  useContentDetailQuery,
  useToggleFavoriteMutation,
  useToggleLikeMutation,
  type ContentDetailResponse,
  type ContentType,
  type ThumbnailAspect,
} from "@/entities/content";
import { toMediaTagImages } from "@/entities/media-book";
import { resolveStartPersona, usePersonasQuery } from "@/entities/persona";
import { useSessionQuery } from "@/entities/session";
import { isApiError } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";
import { expandAuthorMacros, resolveAuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { CharacterChatHistoryLink } from "./CharacterChatHistoryLink";
import { CharacterPlayBar } from "./CharacterPlayBar";
import { ContentActionsMenu } from "./ContentActionsMenu";
import { ContentDetailModalShell } from "./ContentDetailModalShell";
import { ContentUnavailableState } from "./ContentUnavailableState";
import { MediaTagText } from "./MediaTagText";
import { StartPersonaRow } from "./StartPersonaRow";
import { StoryDetailBody } from "./StoryDetailBody";
import { StoryPlayBar } from "./StoryPlayBar";
import { VersionHistoryModal } from "./VersionHistoryModal";
import { applyLikeResult } from "../lib/applyLikeResult";
import { useContentEditingViewport } from "../lib/useContentEditingViewport";

type ContentDetailViewProps = {
  id: string;
  /** content 도착 전(스켈레톤)에는 실제 타입을 모르므로 호출부가
   * 힌트로 넘긴다. 값이 틀려도 스켈레톤 비율만 잠깐 틀리고 도착 시 실제 타입으로 뛴다 — 조회·표시
   * 로직에는 절대 쓰지 않는다(아래에서는 전부 `content.type`을 쓴다). */
  type: ContentType;
  variant: "modal" | "page";
  comments?: ReactNode;
};

const UPDATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

const TYPE_ICON: Record<ContentType, LucideIcon> = {
  character: UserRound,
  story: BookOpen,
};

// 캐릭터(1열)는 모바일에서 `w-full` 그대로, 데스크톱은 높이 예산
// 60dvh가 단일 소스(1:1이라 폭 상한도 같은 값). `max-height`가 아니라 `max-width`로 거는 이유:
// `aspect-ratio` + `w-full` 상태에서 `max-height`는 폭을 줄이지 않아 비율이 깨지고 `object-cover`가
// 다시 자른다.
const CHARACTER_HERO_WIDTH_CLASS = "sm:max-w-[60dvh]";

// 스토리(2열)는 우측 열과 나란히 두므로 높이가 아니라 고정 폭이
// 예산이다: `sm:w-64`(256px) × `aspect-story`(2:3) = 256×384. 예전 높이 캡(`sm:max-w-[40dvh]`)은 폭이
// 이미 고정인 2열 레이아웃에서는 의미가 없어져 뺐다.
const STORY_HERO_WIDTH_CLASS = "sm:w-64 sm:shrink-0";

// 좋아요/즐겨찾기 토글은 연타 방지를 위해 네트워크 호출만 디바운스하고,
// 화면 표시는 isLikeDesired/isFavoriteDesired로 매 클릭마다 즉시 반영한다.
const TOGGLE_SYNC_DEBOUNCE_MS = 400;

/** hero 웰·스켈레톤의 채움. 모달은 `DialogContent`(`popover`) 위라 `muted`가 표면과 같은 값이 되어
 * 1.0000:1로 사라지므로 `secondary`를 쓰고, 페이지는 `background` 위라 `muted`가 맞다
 * (DESIGN.md Colors 절의 "표면 위 채움 규칙"). */
const SURFACE_FILL_CLASS = {
  modal: "bg-secondary",
  page: "bg-muted",
} as const satisfies Record<ContentDetailViewProps["variant"], string>;

/** 모달/풀페이지 공용 상세 콘텐츠. 카드가 있는 모든 리스트
 * (홈, 프로필)는 이 컴포넌트를 직접 렌더링하지 않고 `useContentDetailModal().open()`만 호출한다.
 * `variant`가 필요한 이유: 플레이 CTA를 하단에 고정하는 방식이
 * 모달(카드 안 flex)과 풀페이지(lg 미만 fixed)에서 구조 자체가 달라 호출부가 명시한다. */
export function ContentDetailView({ id, type, variant, comments }: ContentDetailViewProps) {
  const detailQuery = useContentDetailQuery(id);
  const editingViewport = useContentEditingViewport();
  const setModalState = useSetAtom(contentDetailModalAtom);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toggleLike = useToggleLikeMutation(id);
  const toggleFavorite = useToggleFavoriteMutation(id);
  const [isLikeDesired, setIsLikeDesired] = useState<boolean | undefined>(undefined);
  const [isFavoriteDesired, setIsFavoriteDesired] = useState<boolean | undefined>(undefined);
  const [isVersionHistoryOpen, setIsVersionHistoryOpen] = useState(false);
  // 스토리 전용 — 시작설정 선택. `StoryDetailBody`(스크롤 영역의 선택기)와 `StoryPlayBar`(하단
  // 고정 바)가 형제로 갈라지면서 상태를 여기서 들고 있어야 서로 공유할 수 있다. 캐릭터는 쓰지
  // 않지만 다른 optimistic override들과 같은 이유로 무조건 호출한다(hooks 규칙).
  const [selectedSetupIdOverride, setSelectedSetupIdOverride] = useState<string | undefined>(undefined);
  // 새 대화를 시작할 대화 프로필 — 본문의 프로필 줄(`StartPersonaRow`)과 하단 플레이 바가 형제라 시작설정 선택과 같은
  // 이유로 여기서 쥔다. undefined 면 기본(`resolveStartPersona`).
  const [chosenPersonaId, setChosenPersonaId] = useState<string | undefined>(undefined);
  const content = detailQuery.data;
  // 방이 없는 화면이라 작가 글의 `{{user}}` 는 지금 시작하면 쓰일 프로필의 이름이다 — 프로필 줄에서 바꾸면 본문도 따라
  // 바뀐다(프로필이 없거나 비로그인이면 작품 기본 이름).
  const isLoggedIn = useSessionQuery().data !== undefined;
  const personaList = usePersonasQuery({ enabled: isLoggedIn }).data;
  const startPersona = isLoggedIn ? resolveStartPersona(personaList, chosenPersonaId) : null;

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

  // 정산 순서: 성공하면 보낸 값을 상세 캐시에 먼저 쓰고 같은 동기 구간에서 낙관값을 푼다. 둘 사이에 await 가
  // 끼면 그 틈의 렌더가 캐시의 옛 값을 그려 버튼이 리페치가 올 때까지 꺼졌다 켜진다(POST/DELETE 가 204 라
  // 새 값을 받으려면 리페치를 기다려야 했다). 무효화는 서버 값 확인용으로 그 뒤 백그라운드에 둔다 — 활성 쿼리의
  // 무효화는 진행 중이던 옛 GET 을 취소하므로, 창 포커스 등으로 먼저 출발한 GET 이 늦게 와 캐시를 되돌리지 못한다.
  // 해제는 호출 단위 `onSettled` 가 아니라 `mutateAsync` 프로미스에 건다 — 호출 단위 콜백은 같은 observer 로
  // 다시 mutate 하면 덮어써지고, 요청 중 언마운트(모달 닫힘)하면 불리지 않는다.
  // 요청 중에는 보내지 않고, deps 에 서버 값과 `isPending` 을 넣어 정산 뒤 다시 따져 본다. 느린 요청 중에
  // 다시 눌러 바뀐 의도가 그 요청이 끝난 뒤에 나가야 화면과 서버가 갈린 채 굳지 않는다. 정산 뒤 낙관값이
  // 서버 값과 같으면 위 조기 반환에 걸려 아무것도 보내지 않는다.
  useDebounce(
    () => {
      if (
        content === undefined ||
        isLikeDesired === undefined ||
        isLikeDesired === content.isLiked ||
        toggleLike.isPending
      )
        return;
      const isNextLiked = isLikeDesired;
      // 정산되는 사이 다시 클릭해 isLikeDesired가 이미 다른 값으로 바뀌었다면(연타) 그 새 의도를 덮어쓰지 않는다.
      const releaseOverride = () => setIsLikeDesired((current) => (current === isNextLiked ? undefined : current));
      void toggleLike.mutateAsync(isNextLiked).then(
        () => {
          queryClient.setQueryData<ContentDetailResponse>(contentKeys.detail(id), (old) =>
            applyLikeResult(old, isNextLiked),
          );
          releaseOverride();
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
        },
        (error: unknown) => {
          toast.error(
            isApiError(error) && error.status === 401
              ? "로그인 후 좋아요를 남길 수 있어요."
              : "좋아요 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
          // 실패하면 캐시를 쓰지 않으므로 낙관값만 풀면 마지막으로 받은 서버 값으로 돌아간다. 실패가 곧 서버에
          // 반영되지 않았다는 뜻은 아니므로(응답만 잃은 경우) 다시 받아 확인한다.
          releaseOverride();
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
        },
      );
    },
    TOGGLE_SYNC_DEBOUNCE_MS,
    [isLikeDesired, content?.isLiked, toggleLike.isPending],
  );

  // 좋아요와 같은 정산 순서·보류 규칙이다(위 주석). 즐겨찾기는 수가 없어 값만 쓴다.
  useDebounce(
    () => {
      if (
        content === undefined ||
        isFavoriteDesired === undefined ||
        isFavoriteDesired === content.isFavorited ||
        toggleFavorite.isPending
      )
        return;
      const isNextFavorited = isFavoriteDesired;
      const releaseOverride = () =>
        setIsFavoriteDesired((current) => (current === isNextFavorited ? undefined : current));
      void toggleFavorite.mutateAsync(isNextFavorited).then(
        () => {
          queryClient.setQueryData<ContentDetailResponse>(contentKeys.detail(id), (old) =>
            old === undefined ? old : { ...old, isFavorited: isNextFavorited },
          );
          releaseOverride();
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
          // `favoriteKeys.list(type)`이 타입별로 캐시를 가른다 — 접두사로
          // 두 타입 모두 무효화한다. 한쪽만 지우면 반대 타입 즐겨찾기 목록이 stale로 남는다.
          void queryClient.invalidateQueries({ queryKey: favoriteKeys.all });
        },
        (error: unknown) => {
          toast.error(
            isApiError(error) && error.status === 401
              ? "로그인 후 즐겨찾기에 담을 수 있어요."
              : "즐겨찾기 처리에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
          releaseOverride();
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(id) });
          void queryClient.invalidateQueries({ queryKey: favoriteKeys.all });
        },
      );
    },
    TOGGLE_SYNC_DEBOUNCE_MS,
    [isFavoriteDesired, content?.isFavorited, toggleFavorite.isPending],
  );

  // 모달은 어느 상태든 같은 [헤더, 스크롤 본문] 틀에 담는다(`ContentDetailModalShell`). 풀페이지는 다이얼로그
  // 밖이라 그 틀(다이얼로그 제목)을 쓰면 Radix가 던지므로 내용만 그대로 낸다.
  if (detailQuery.isPending) {
    const skeleton = <ContentDetailSkeleton type={type} variant={variant} />;
    return variant === "modal" ? <ContentDetailModalShell isTitlePending>{skeleton}</ContentDetailModalShell> : skeleton;
  }

  if (detailQuery.isError) {
    const message = (
      <p className="p-6 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
    return variant === "modal" ? <ContentDetailModalShell>{message}</ContentDetailModalShell> : message;
  }

  if (content === undefined) return variant === "modal" ? <ContentDetailModalShell /> : null;

  const access = toContentAccessStatus(content.accessStatus);

  // `kind` 검사는 `canViewDetailPage`가 이미 포함하지만(restricted/deleted면 false) 그 함수는 타입
  // 술어가 아니다 — 아래에서 `access.visibility`(전환 메뉴의 "현재 값")를 쓰려면 여기서 좁혀야 한다.
  if (access.kind !== "accessible" || !canViewDetailPage(access, content.isOwner)) {
    const unavailable = <ContentUnavailableState access={access} />;
    return variant === "modal" ? <ContentDetailModalShell>{unavailable}</ContentDetailModalShell> : unavailable;
  }

  const isLiked = isLikeDesired ?? content.isLiked;
  const likeCount = content.likeCount + optimisticDelta(isLiked, content.isLiked);
  const isFavorited = isFavoriteDesired ?? content.isFavorited;
  const selectedSetupId = selectedSetupIdOverride ?? content.startingSetups?.[0]?.id;
  const macroNames = resolveAuthorMacroNames({
    personaName: startPersona?.name ?? null,
    defaultUserName: content.defaultUserName,
    contentType: content.type,
    contentName: content.name,
  });

  let footer: ReactNode;
  switch (content.type) {
    case "story":
      footer = (
        <StoryPlayBar
          contentId={content.id}
          startingSetups={content.startingSetups ?? []}
          selectedSetupId={selectedSetupId}
          personaId={startPersona?.id}
          macroNames={macroNames}
          onRestoreSetup={setSelectedSetupIdOverride}
        />
      );
      break;
    case "character":
      footer = <CharacterPlayBar contentId={content.id} personaId={startPersona?.id} />;
      break;
    default:
      assertNever(content.type);
  }

  // hero 비율은 카드 그리드와 같은 도메인→표현 매핑
  // (`toThumbnailAspect`)을 재사용한다: 캐릭터 1:1, 스토리 2:3.
  const heroAspect = toThumbnailAspect(content.type);
  const TypeIcon = TYPE_ICON[content.type];

  // `access.kind === "accessible"`로 이미 좁혀진 자리다(위 early return) — 그래서 여기 오는 콘텐츠의
  // 모더레이션 상태는 `normal`이다. 상세 응답은 `moderationStatus`를 따로 내려주지 않고 `accessStatus`로
  // 접어 주므로 이 좁힘이 그 값의 유일한 출처다. 모달은 이 메뉴를 헤더에, 풀페이지는 본문 메타 첫 줄에 둔다.
  const actionsMenu = (
    <ContentActionsMenu
      contentId={content.id}
      creatorUserId={content.creatorUserId}
      isOwner={content.isOwner}
      visibility={access.visibility}
      moderationStatus="normal"
      novelPermission={content.novelPermission}
      triggerSize={variant === "modal" ? "icon-sm" : "icon"}
    />
  );

  // `p-1`은 패딩 없는 스크롤 상자 안에서 가장자리 컨트롤의 포커스 링이 잘리지 않게 하던 여유다. 모달의 스크롤
  // 본문(`DialogBody`)은 그 여유를 스스로 주므로 모달에서는 빼서 본문 왼쪽 끝을 헤더 제목 왼쪽 끝에 맞추고,
  // 풀페이지는 화면이 바뀌지 않게 그대로 둔다.
  const body = (
    <article className={cn("flex flex-col gap-5", variant === "page" && "p-1")}>
      {/* 스토리는 ≥sm에서 hero+메타를 가로 2열로 두고(사용자 피드백
          "메타데이터가 이미지 오른쪽"), 캐릭터는 지금처럼 1열을 유지한다. */}
      <div
        className={cn("flex flex-col gap-5", content.type === "story" && "sm:flex-row sm:items-start sm:gap-6")}
      >
        <div
          className={toHeroClassName(
            content.type,
            heroAspect,
            cn("overflow-hidden rounded-lg", SURFACE_FILL_CLASS[variant]),
          )}
        >
          {/* 상세(페이지·모달 공용)의 첫 화면 주인공 이미지라 모달 그리드와 같은 이유로 lazy 제외. */}
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
                <TypeIcon aria-hidden className="size-3.5" />
                {TYPE_LABEL[content.type]}
              </span>

              {variant === "page" && actionsMenu}
            </div>

            {/* 모달에서는 헤더의 다이얼로그 제목이 작품명이라 본문에 다시 쓰지 않는다. */}
            {variant === "page" && (
              <h1 className="text-xl font-bold tracking-tight text-foreground">{content.name}</h1>
            )}

            <Link
              to="/profile/$userId"
              params={{ userId: content.creatorUserId }}
              onClick={() => setModalState(undefined)}
              // 보더 없는 텍스트 컨트롤이라 반투명 헤일로만으로는 포커스가 배경 대비 3:1 에 못 미친다 — 불투명 1px
              // 아웃라인이 그 몫을 진다(DESIGN.md Buttons 절의 Focus). 아래 해시태그도 같다.
              className="w-fit rounded-sm text-sm text-muted-foreground hover:underline focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
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
                      // 해시태그 클릭 시 홈으로 이동해 해당 해시태그로 필터링한다. 유형도 이 작품의 유형으로
                      // 싣는다 — 파라미터 없는 `/`는 스토리라, 빼면 캐릭터 태그로 스토리 목록을 걸러 빈 화면이 된다.
                      void navigate({ to: "/", search: { hashtag: tag, type: toHomeTypeParam(content.type) } });
                    }}
                    // 터치에서는 높이만 40px 로 키운다 — 줄바꿈된 태그 줄 사이 간격이 6px 라, 보이는 크기를 두고 누르는
                    // 영역만 넓히면 위아래 줄의 영역이 겹친다. 모달은 높이를 맞출 스켈레톤이 없어 높이가 바뀌어도 된다.
                    className="inline-flex items-center rounded-sm text-xs text-muted-foreground hover:underline focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 좋아요·즐겨찾기는 `ghost` 버튼이라 포커스(불투명 보더 + 헤일로)와 누르는 높이를 프리미티브에서 얻는다.
              글자·글리프 사이 보이는 간격은 버튼으로 바꾸기 전과 같은 16px 로 맞춘다. 버튼은 안쪽 여백이 패딩 8px + 투명
              보더 1px(포커스 때 `ring` 이 되는 그 보더) = 9px 라, 줄 간격을 8px 로 줄이고 좋아요를 1px(`-ml-px`) 당겨
              대화수 → 하트가 8 − 1 + 9 = 16px, 즐겨찾기를 10px(`-ml-2.5`) 당겨 좋아요 수 → 별이 9 + 8 − 10 + 9 = 16px 다.
              터치에서는 별 버튼이 40px 정사각이라 안쪽 여백이 12px 로 늘어, 좋아요 오른쪽 패딩을 4px 로 줄이고 당김을
              9px 로 바꿔 5 + 8 − 9 + 12 = 16px 를 지킨다(Tailwind 간격 단계가 2px 라 홀수 합을 맞출 단계가 없어 이 한 값만
              임의값이다). 당김 때문에 두 버튼 상자는 투명 보더 몇 px 만 겹치고, 누르는 영역은 둘 다 40px 를 넘는다.
              hover 는 `secondary` —
              모달 표면(`popover`) 위에서 ghost 기본 hover(`muted`)는 값이 같아 사라진다. `font-normal` 은 버튼의
              medium 을 옆 대화수와 같은 본문 굵기로 되돌린다. */}
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <MessageCircle aria-hidden className="size-4" />
              {/* 아이콘이 숨겨져 숫자만 읽히므로 무엇의 수인지 붙인다 — 카드 지표와 같은 이름("대화수")이다. */}
              <span className="sr-only">대화수 {content.chatCount.toLocaleString()}</span>
              <span aria-hidden>{content.chatCount.toLocaleString()}</span>
            </span>

            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={isLiked}
              onClick={() => setIsLikeDesired((current) => !(current ?? content.isLiked))}
              className={cn(
                "-ml-px gap-1.5 px-2 text-sm font-normal text-muted-foreground hover:bg-secondary pointer-coarse:h-10 pointer-coarse:pr-1",
                isLiked && "text-primary hover:text-primary",
              )}
            >
              <Heart aria-hidden className={cn("size-4", isLiked && "fill-primary")} />
              {likeCount.toLocaleString()}
              <span className="sr-only">{isLiked ? "좋아요 취소" : "좋아요"}</span>
            </Button>

            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={isFavorited}
              onClick={() => setIsFavoriteDesired((current) => !(current ?? content.isFavorited))}
              className={cn(
                "-ml-2.5 px-2 text-sm font-normal text-muted-foreground hover:bg-secondary pointer-coarse:-ml-[9px] pointer-coarse:size-10 pointer-coarse:px-0",
                isFavorited && "text-primary hover:text-primary",
              )}
            >
              <Star aria-hidden className={cn("size-4", isFavorited && "fill-primary")} />
              <span className="sr-only">{isFavorited ? "즐겨찾기 해제" : "즐겨찾기"}</span>
            </Button>

          </div>

          <p className="text-sm font-medium text-foreground">{expandAuthorMacros(content.oneLiner, macroNames)}</p>
        </div>
      </div>

      {/* 우측 열 폭이 ~350px인데 본문이 `text-sm`이라 한 줄에 21자밖에
          안 들어간다. 긴 산문은 2열에 넣지 않고 전폭으로 둔다. */}
      {/* 글 속 미디어 북 태그 자리에만 그림 블록이 선다. 그림 자리 면은 모달 표면 위에서 `muted` 가 사라지므로 변형을
          따라 고른다. */}
      <MediaTagText
        text={content.detailDescription}
        images={toMediaTagImages(content.mediaTagImages)}
        names={macroNames}
        className="whitespace-pre-wrap text-sm text-muted-foreground"
        surface={variant === "modal" ? "secondary" : "muted"}
      />

      {content.type === "story" && (
        <StoryDetailBody
          startingSetups={content.startingSetups ?? []}
          mediaTagImages={toMediaTagImages(content.mediaTagImages)}
          macroNames={macroNames}
          selectedSetupId={selectedSetupId}
          onSelectedSetupIdChange={setSelectedSetupIdOverride}
        />
      )}
      {content.type === "character" && <CharacterChatHistoryLink contentId={content.id} />}

      {/* 시작 준비(시작 상황·내 대화 목록)의 마지막 줄이라 업데이트(참고 정보)보다 위다. 프로필이 없으면 그리지 않는다 —
          그 사람은 플레이를 누를 때 이름부터 받는다. */}
      {personaList !== undefined && startPersona !== null && (
        <StartPersonaRow personaList={personaList} startPersona={startPersona} onSelect={setChosenPersonaId} />
      )}

      {/* 업데이트 이력은 대화수·좋아요 같은 **지표가 아니다** — 통계 줄에 섞여 있어서 2열로 좁아진
          우측 열에서 자리를 다퉜다(2026-09-15 실사용 제보). 참고 정보라 플레이로 가는 길(시작설정
          선택)을 끊지 않게 맨 아래에 둔다.
          hover 표면이 `bg-muted`가 아닌 이유: `--muted`와 `--popover`가 다크 0.210 / 라이트 0.970으로
          **값이 같아** 모달 안에서 hover가 통째로 사라진다(같은 함정을 Slider 트랙에서 겪었다).
          `secondary`는 페이지 배경·모달 표면 양쪽에서 살아남는다. hover에서 글자도 `foreground`로 올린다 —
          라이트 `muted-foreground` on `secondary`는 4.29:1로 AA 미달이다(DESIGN.md Colors 절의 "표면 위 채움 규칙").
          포커스 때 보더를 `ring` 으로 올린다 — 무채색 보더 위 반투명 헤일로만으로는 3:1 에 못 미친다. */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">업데이트</h2>
        <button
          type="button"
          onClick={() => setIsVersionHistoryOpen(true)}
          className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-left text-sm text-muted-foreground motion-safe:transition-colors hover:bg-secondary hover:text-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
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

  // 플레이 CTA를 스크롤 영역 밖으로 뽑아 하단에 고정한다.
  if (variant === "modal") {
    // 모달은 폭과 무관하게 전 폭에서 고정한다(분기 없음) — 스크롤 본문(`DialogBody`)이 있으면
    // `DialogContent`가 최대 높이가 있는 flex 컬럼이 되므로, 플레이 바는 그 컬럼의 마지막 아이템으로 바닥에
    // 남는다. 카드 안 flex 배치라 겹칠 다른 fixed/absolute 레이어가 없으므로 z-index 경쟁이 없다.
    return (
      <ContentDetailModalShell
        title={content.name}
        actions={actionsMenu}
        footer={
          <div data-content-play-bar className="-mx-4 -mb-4 shrink-0 rounded-b-xl border-t border-border bg-popover p-4 pb-4-safe">
            {footer}
          </div>
        }
      >
        {body}
        {comments}
      </ContentDetailModalShell>
    );
  }

  return (
    <>
      {body}
      {/* 풀페이지는 자연 문서 스크롤이라 모달과 같은 flex 트릭을 못 쓴다 — `lg` 미만에서만
          뷰포트 기준 `fixed` 바로, `lg` 이상은 지금처럼 본문 안 인라인으로 되돌아간다(넓은 화면의
          전폭 고정 바는 DESIGN.md가 경계하는 "상시 크롬"에 가깝다는 판단, 확정 결정).
          z-40: 헤더(`z-30`, sticky)와는 화면 위/아래로 겹칠 일이 없어 순서가 기능에 영향을 주지
          않지만, 이 화면에 뜨는 Dialog/Sheet(`z-50`)는 항상 이 바 위를 덮어야 하므로 그 아래로 둔다. */}
      <div data-content-play-bar style={editingViewport ? { bottom: editingViewport.bottomInset } : undefined}
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background p-4 pb-4-safe lg:static lg:inset-auto lg:z-auto lg:mt-5 lg:border-t-0 lg:bg-transparent lg:p-0 lg:pb-0">
        {footer}
      </div>
      {comments}
    </>
  );
}

// 실제 hero와 스켈레톤이 이 함수 하나를 같이 써야 도착 시 폭이 안
// 밀린다(스켈레톤이 실제와 다른 모양이면 도착 순간 화면이 밀린 전례).
function toHeroClassName(type: ContentType, aspect: ThumbnailAspect, visualClass: string): string {
  switch (type) {
    case "character":
      return cn("mx-auto w-full", visualClass, toThumbnailAspectClass(aspect), CHARACTER_HERO_WIDTH_CLASS);
    case "story":
      return cn("w-full", visualClass, toThumbnailAspectClass(aspect), STORY_HERO_WIDTH_CLASS);
    default:
      return assertNever(type);
  }
}

// content 도착 전이라 `content.type`을 못 읽으므로 호출부가 넘긴
// `type`(모달: 상태에 이미 있음, 페이지: URL 세그먼트)으로 같은 비율을 흉내 낸다. 어긋나면 도착 시
// 화면이 밀린다.
function ContentDetailSkeleton({ type, variant }: Pick<ContentDetailViewProps, "type" | "variant">) {
  const heroAspect = toThumbnailAspect(type);
  const fill = SURFACE_FILL_CLASS[variant];
  return (
    // 본문과 같은 이유로 `p-1`은 풀페이지에만 둔다.
    <div className={cn("flex flex-col gap-4", variant === "page" && "p-1")}>
      {/* 실제 본문과 같은 2열 분기(스토리만 ≥sm에서 flex-row)를
          흉내 내지 않으면 도착 시 화면이 밀린다. */}
      <div className={cn("flex flex-col gap-4", type === "story" && "sm:flex-row sm:items-start sm:gap-6")}>
        <div className={toHeroClassName(type, heroAspect, cn("animate-pulse rounded-lg", fill))} />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className={cn("h-6 w-2/3 animate-pulse rounded", fill)} />
          <div className={cn("h-4 w-1/3 animate-pulse rounded", fill)} />
        </div>
      </div>
      <div className={cn("h-20 w-full animate-pulse rounded", fill)} />
    </div>
  );
}

/** 낙관적 토글이 서버 값과 갈릴 때만 카운트를 ±1 한다 — 서버 카운트를 다시 받기 전까지 화면만
 * 앞서간다. 중첩 삼항으로 쓰면 "같으면 0"과 "다르면 방향"이라는 두 질문이 한 줄에 겹친다. */
function optimisticDelta(optimistic: boolean, server: boolean): number {
  if (optimistic === server) return 0;
  return optimistic ? 1 : -1;
}
