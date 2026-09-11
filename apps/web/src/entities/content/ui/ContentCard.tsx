import { useId, type ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, Eye, Heart, ImageOff, MessageCircle, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

import { toThumbnailAspectClass, type ThumbnailAspect } from "../model/cardLayout";
import type { ContentType, ContentVisibility } from "../model/content";

/** 카드에 다는 배지. 타입(무엇인지)과 상태(어디에 놓여 있는지)를 한 배열로 받아 순서는 호출부가 정한다.
 * `unpublished`(미등록)는 한 번도 발행된 적 없는 초안이라 공개범위 자체가 없다 — 그래서 다른 상태 배지와
 * 함께 달리지 않고 혼자 온다(US-008). */
export type ContentCardTag = ContentType | ContentVisibility | "restricted" | "unpublished";

const TAG_LABEL: Record<ContentCardTag, string> = {
  character: "캐릭터",
  story: "스토리",
  public: "공개",
  link: "링크공개",
  private: "비공개",
  restricted: "이용제한",
  unpublished: "미등록",
};

// DESIGN.md §Status badges — 타입은 `secondary` 채움 + 14px 아이콘, 이용제한은 `destructive/10` 틴트다
// (이 시스템에 솔리드 레드 채움은 없다).
//
// 중립 상태(공개/링크공개/비공개/미등록)는 DESIGN.md가 `bg-muted`로 적어 뒀지만 **채움 대신 윤곽**으로 쓴다.
// 카드 껍데기가 걷히기 전엔 `bg-muted` 채움이 카드 표면과 같은 값이 되는 순간이 있었다 — 카드가 `bg-card`
// 였을 땐 rest에서, `bg-background`+`hover:bg-muted`였을 땐 hover에서(둘 다 스크린샷 픽셀 실측 정확히
// 1.0000:1로 알약이 사라졌다). 카드 표면 자체가 사라진 지금은 그 충돌이 없지만, 남는 **타입=채움 /
// 상태=윤곽** 형태 구분은 여전히 유효한 위계 신호라 유지한다(US-008). `border`(다크 0.300 / 라이트 0.890)는
// 이미 명도 사다리에 있는 값이라 새 중간값을 발명하지 않는다.
const TAG_CLASS: Record<ContentCardTag, string> = {
  character: "bg-secondary text-secondary-foreground",
  story: "bg-secondary text-secondary-foreground",
  public: "border border-border text-muted-foreground",
  link: "border border-border text-muted-foreground",
  private: "border border-border text-muted-foreground",
  restricted: "bg-destructive/10 text-destructive-text",
  unpublished: "border border-border text-muted-foreground",
};

const TAG_ICON: Partial<Record<ContentCardTag, LucideIcon>> = {
  character: UserRound,
  story: BookOpen,
};

/** 카드에 얹는 지표. `viewCount` 하나만 오고 `author`가 없으면(프로필) `조회수 {n}` 평문 그대로 두고,
 * `author`가 함께 오면(홈·즐겨찾기) `Eye` 아이콘 + `·` + 작가명을 한 줄로 합친다(card-grid-goal-prompt.md
 * D-4). 셋이 다 오면(`/my`) 라벨을 아이콘으로 바꿔 스크린리더에만 한국어 이름을 남긴다.
 *
 * 셋을 아이콘으로 바꾼 이유는 공간이 아니다 — 390px 2열(카드 내부폭 139px)에서 세 지표는 **아이콘으로 줄여도
 * 203px가 필요해 어차피 두 줄로 접힌다**(실측). 접히는 것 자체는 파손이 아니라서 그대로 두고, 아이콘을 고른
 * 진짜 이유는 어휘 일치다 — `ContentDetailView`가 이미 `Eye`/`MessageCircle`/`Heart`를 같은 뜻으로 쓴다.
 *
 * 화면에 보이는 숫자는 `formatCompactCount`로 축약한다(`46.8K`) — 390px 3열(카드 폭 111.33px)에서 자릿수가
 * 늘수록 옆 텍스트(작가명)를 잠식해서다. `ContentDetailView`는 폭 제약이 없어 `toLocaleString()` 전체
 * 숫자를 그대로 쓴다(축약하지 않는다) — 목록과 상세는 여기서 의도적으로 갈린다. 스크린리더에는 정밀도
 * 손실 없이 전체 숫자를 남긴다(아래 각 렌더 지점의 `sr-only`/`aria-hidden` 쌍). */
export type ContentCardMetrics = {
  viewCount: number;
  chatCount?: number;
  likeCount?: number;
};

export type ContentCardProps = {
  thumbnailUrl: string | null;
  /** card-grid-techspec.md T-3 — 표시 비율. **기본값을 두지 않는다**: 두면 빠뜨린 호출부가 조용히
   * `square`가 된다. 도메인(`ContentType`) → 표현 매핑은 카드가 아니라 `toThumbnailAspect`가 진다. */
  thumbnailAspect: ThumbnailAspect;
  title: string;
  metrics?: ContentCardMetrics;
  /** 지표 대신(또는 지표가 없을 때) 그 자리에 놓는 한 줄. `/my`의 초안 카드가 "… 수정"을 여기 넣는다 —
   * 초안은 지표가 없어 이 줄이 없으면 제목과 배지 사이가 통째로 비고, 목록의 정렬 키(수정일)를
   * 화면에서 확인할 방법도 사라진다(US-008). */
  metaLabel?: string;
  author?: { name: string; profileUrl: string };
  tags?: ContentCardTag[];
  /** 카드 안에서 카드와 다른 동작을 하는 요소. "⋯" 메뉴라면 **직접 만들지 말고 `ContentCardActionMenu`를
   * 쓴다** — 클릭 카드 안에서 지켜야 할 것(click·keydown 양쪽 stopPropagation, hover 토큰, 메뉴 폭)이
   * 거기 다 들어 있다. 다른 것을 넣는다면 click과 keydown을 모두 `stopPropagation` 해야 한다
   * (이유는 `apps/web/CLAUDE.md`의 "클릭 카드" 항목). */
  actions?: ReactNode;
  /** US-013 — 첫 화면에 보이는 카드만 lazy를 풀고 즉시 로드한다. 그리드가
   * 타입별로 갈리므로(캐릭터 2/3/4 · 스토리 3/4/5) 호출부는 **`toPriorityCount(aspect)`** 를 쓴다 —
   * 그 사다리의 최대 열 수다. **손으로 적은 숫자를 쓰지 말 것**: 2026-09-11 에 스토리 사다리를 바꿨을 때
   * 호출부 4곳의 `index < 4` 가 그대로 남아 md 이상에서 첫 줄 마지막(5번째) 카드가 lazy 로 빠졌다.
   * 좁은 화면에선 실제 열 수보다 많이 당겨지지만(2열이면 2장이 과하게) 그건 원래 감수하던 오차다. */
  priority?: boolean;
  /** LCP 후보 1장(`index === 0`)에만 준다 — 여러 장에 주면 우선순위 신호가 희석돼 의미가 없다. */
  isLcpCandidate?: boolean;
  /** card-grid-techspec.md T-5 — `ContentCardSkeleton`이 "보이지 않는 실제 카드"를 `invisible`로
   * 겹칠 때만 쓴다. 그 외 호출부는 쓰지 않는다. */
  className?: string;
  /** 위와 같은 용도 — 스켈레톤의 더미 카드를 포커스·a11y 트리에서 뺀다. */
  inert?: boolean;
  onClick: () => void;
  onAuthorClick?: () => void;
};

/** techspec-home-discovery.md §3 — 홈/즐겨찾기/프로필/내 작품 4곳이 공용으로 쓰는 카드. 카드 전체가 클릭 영역
 * (상세 모달 오픈, US-042)이며, `onAuthorClick`이 있으면 작가명만, `actions`가 있으면 그 영역만 별도 클릭
 * 영역이 된다(홈의 크리에이터 필터 US-044, 프로필의 공개범위 메뉴 US-115) — 그래서 바깥 컨테이너는
 * `<button>`이 아니라 `role="button"` `div`를 쓴다(버튼 안에 버튼을 중첩할 수 없다).
 *
 * 카드에는 표면(배경·보더·hover)이 없다 — 썸네일이 곧 콘텐츠라 카드 껍데기를 걷어냈다(2026-09-11
 * 사용자 결정). `active:translate-y-px`만 터치의 유일한 피드백으로 남는다(`apps/web/CLAUDE.md`). */
export function ContentCard({
  thumbnailUrl,
  thumbnailAspect,
  title,
  metrics,
  metaLabel,
  author,
  tags,
  actions,
  priority = false,
  isLcpCandidate = false,
  className,
  inert,
  onClick,
  onAuthorClick,
}: ContentCardProps) {
  const id = useId();

  // card-grid-goal-prompt.md D-4 — `viewCount` 단일 지표(대화수·좋아요 없음) + `author` 조합일 때만
  // 조회수·작가명을 한 줄로 합친다. 프로필은 `author`를 안 넘기고(`ContentSummary`에 작가 필드 자체가
  // 없다), `/my`는 지표 3개라 이 조건에 걸리지 않아 둘 다 현행 동작 그대로다.
  const isCombinedMetaLine =
    metrics !== undefined &&
    metrics.chatCount === undefined &&
    metrics.likeCount === undefined &&
    author !== undefined;

  // 카드 이름을 **내용 계산에 맡기지 않고** 자기 자식들을 직접 가리킨다. 계산에 맡기면 `actions`의 "⋯"
  // 버튼 라벨까지 이름에 빨려 들어가서, 그 버튼에 작품 이름을 넣는 순간 카드가 제목을 두 번 읽는다
  // (실측: `"미아 미아 더보기 조회수 …"`). 그렇다고 카드에 `aria-label`을 걸면 지표·배지가 이름에서
  // 통째로 사라진다(US-008에서 그래서 기각했다). `aria-labelledby`는 **참조한 노드만** 훑으므로 둘 다
  // 피한다 — 지표·배지는 남고 "⋯"만 빠져서, 버튼 쪽이 `"{제목} 더보기"`로 서로 구별될 수 있게 된다
  // (그리드에 "더보기" 32개가 놓이면 스크린리더 로터로는 아무것도 못 고른다).
  //
  // 렌더되지 않은 자식의 id를 남겨 두면 그 참조만 조용히 버려지는 게 아니라 이름 계산이 어긋나므로,
  // **실제로 그린 것만** 넣는다.
  const labelledBy = [
    `${id}-title`,
    metrics ? `${id}-metrics` : "",
    metaLabel ? `${id}-meta` : "",
    author ? `${id}-author` : "",
    tags && tags.length > 0 ? `${id}-tags` : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      role="button"
      tabIndex={0}
      aria-labelledby={labelledBy}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onClick();
      }}
      inert={inert}
      className={cn(
        // 카드 껍데기(border·배경·hover)가 없다 — 썸네일이 카드 가장자리와 flush하다. `rounded-xl`은
        // 표면을 자르기 위해서가 아니라 focus-visible 링의 모양을 잡기 위해 남는다. `gap-2`는 썸네일과
        // 텍스트 사이 8px.
        "flex w-full cursor-pointer flex-col gap-2 rounded-xl text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px",
        className,
      )}
    >
      {/* 웰은 `bg-muted`가 아니라 `bg-secondary`다 — 카드 껍데기가 사라져 웰은 이제 페이지 배경
          (`bg-background`, 다크 0.160) 위에 직접 놓인다. `bg-secondary`(0.260)는 그 위에서 여전히
          보이고, 썸네일이 아직 없는 초안 카드(US-007의 지연 생성이 만드는 정상 상태)에서만 보이는
          자리라 그때가 곧 전부다.
          `rounded-xl`·`border`·`overflow-hidden`을 웰이 직접 갖는다 — 네 모서리 모두 둥글어야 해서
          더는 부모의 클립에 기대지 않는다. 테두리는 `border-border`가 아니라 `border-foreground/10`이다
          — 불투명 무채색 보더(다크 oklch 0.300)를 이미지 위에 얹으면 밝은 이미지에선 거의 안 보이고
          어두운 이미지에서만 보여 이미지마다 테두리 유무가 갈린다. `foreground/10`은 `DESIGN.md` §4의
          기존 어휘(떠 있는 팝오버의 `ring-1 ring-foreground/10`, The Ring-Not-Shadow Rule)를 재사용한다. */}
      <div
        className={cn(
          toThumbnailAspectClass(thumbnailAspect),
          "overflow-hidden rounded-xl border border-foreground/10 bg-secondary",
        )}
      >
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
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
        {/* `gap-2`는 잘린 제목의 말줄임 `…`과 `actions`의 "⋯"를 갈라 놓기 위한 것이다
            (`apps/web/CLAUDE.md`의 "잘린 제목 옆에 ⋯" 항목에 실측치와 함께 있다). */}
        <div className="flex items-center gap-2">
          <p
            id={`${id}-title`}
            className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground"
          >
            {title}
          </p>
          {actions}
        </div>

        {isCombinedMetaLine && metrics && author ? (
          <ContentCardViewsAndAuthor
            id={id}
            viewCount={metrics.viewCount}
            author={author}
            onAuthorClick={onAuthorClick}
          />
        ) : (
          metrics && <ContentCardMetricList id={`${id}-metrics`} metrics={metrics} />
        )}

        {/* `break-keep`이 여기(프리미티브)에 있는 이유: 이 줄은 호출부가 **문자열로만** 넘기는 자리라
            다이얼로그 본문처럼 호출부에서 클래스를 얹을 수가 없다. 없으면 390px 카드(내부폭 139px)에서
            `편집한 내용은 발행해야 반영` / `돼요`로 어절 한가운데가 갈렸다(US-010 실측) — 하필 무엇을
            해야 하는지를 말하는 그 동사다. 붙인 뒤 `편집한 내용은` / `발행해야 반영돼요`로 어절 경계에서
            접힌다. `truncate`인 제목·작가명과 달리 이 줄만 여러 줄이 될 수 있어 이 줄에만 건다. */}
        {metaLabel && (
          <p id={`${id}-meta`} className="text-xs break-keep text-muted-foreground">
            {metaLabel}
          </p>
        )}

        {!isCombinedMetaLine &&
          author &&
          (onAuthorClick ? (
            <button
              id={`${id}-author`}
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onAuthorClick();
              }}
              className="w-fit truncate text-left text-xs text-muted-foreground hover:underline"
            >
              {author.name}
            </button>
          ) : (
            <p id={`${id}-author`} className="truncate text-xs text-muted-foreground">
              {author.name}
            </p>
          ))}

        {tags && tags.length > 0 && (
          <div id={`${id}-tags`} className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <ContentCardTagBadge key={tag} tag={tag} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

type ContentCardViewsAndAuthorProps = {
  id: string;
  viewCount: number;
  author: { name: string; profileUrl: string };
  onAuthorClick?: () => void;
};

/** card-grid-goal-prompt.md D-4 — 조회수·작가명 한 줄. `-metrics`/`-author` 두 id를 그대로 유지한다
 * (labelledBy 계약, `ContentCard` 상단 주석). 조회수 묶음은 `shrink-0`, 작가명이 `min-w-0` + `truncate`를
 * 진다 — 긴 쪽은 작가명이어야 한다. */
function ContentCardViewsAndAuthor({ id, viewCount, author, onAuthorClick }: ContentCardViewsAndAuthorProps) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span id={`${id}-metrics`} className="inline-flex shrink-0 items-center gap-1">
        <Eye aria-hidden className="size-3.5" />
        <span className="sr-only">조회수 {viewCount.toLocaleString()}</span>
        <span aria-hidden>{formatCompactCount(viewCount)}</span>
      </span>
      <span aria-hidden>·</span>
      {onAuthorClick ? (
        <button
          id={`${id}-author`}
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onAuthorClick();
          }}
          className="min-w-0 truncate text-left hover:underline"
        >
          {author.name}
        </button>
      ) : (
        <span id={`${id}-author`} className="min-w-0 truncate">
          {author.name}
        </span>
      )}
    </div>
  );
}

function ContentCardMetricList({ id, metrics }: { id: string; metrics: ContentCardMetrics }) {
  if (metrics.chatCount === undefined && metrics.likeCount === undefined) {
    return (
      <p id={id} className="text-xs text-muted-foreground">
        {"조회수 "}
        <span className="sr-only">{metrics.viewCount.toLocaleString()}</span>
        <span aria-hidden>{formatCompactCount(metrics.viewCount)}</span>
      </p>
    );
  }

  return (
    <div
      id={id}
      className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground"
    >
      <ContentCardMetric Icon={Eye} label="조회수" value={metrics.viewCount} />
      {metrics.chatCount !== undefined && (
        <ContentCardMetric Icon={MessageCircle} label="대화수" value={metrics.chatCount} />
      )}
      {metrics.likeCount !== undefined && (
        <ContentCardMetric Icon={Heart} label="좋아요" value={metrics.likeCount} />
      )}
    </div>
  );
}

type ContentCardMetricProps = { Icon: LucideIcon; label: string; value: number };

function ContentCardMetric({ Icon, label, value }: ContentCardMetricProps) {
  return (
    <span className="inline-flex items-center gap-1">
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">
        {label} {value.toLocaleString()}
      </span>
      <span aria-hidden>{formatCompactCount(value)}</span>
    </span>
  );
}

function ContentCardTagBadge({ tag }: { tag: ContentCardTag }) {
  const Icon = TAG_ICON[tag];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-badge font-medium",
        TAG_CLASS[tag],
      )}
    >
      {Icon && <Icon aria-hidden className="size-3.5" />}
      {TAG_LABEL[tag]}
    </span>
  );
}
