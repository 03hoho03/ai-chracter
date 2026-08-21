import type { ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, Eye, Heart, ImageOff, MessageCircle, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";

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
// 중립 상태(공개/링크공개/비공개/미등록)는 DESIGN.md가 `bg-muted`로 적어 뒀지만 **채움 대신 윤곽**으로 쓴다 —
// `bg-muted` 채움은 카드 표면과 같은 값이 되는 순간이 반드시 있어서다. 카드가 `bg-card`였을 땐 rest에서
// (`--muted` == `--card`), 지금처럼 `bg-background`로 바뀐 뒤엔 `hover:bg-muted`가 걸리는 hover에서 —
// 둘 다 스크린샷 픽셀 실측 **정확히 1.0000:1**로 알약이 통째로 사라진다. 반면 윤곽은 hover에서도 살아남는다
// (다크 1.3076 / 라이트 1.2699). `border`(다크 0.300 / 라이트 0.890)는 이미 명도 사다리에 있는 값이라 새
// 중간값을 발명하지 않고, 결과적으로 **타입=채움 / 상태=윤곽**으로 형태가 갈려 위계가 생긴다(US-008).
const TAG_CLASS: Record<ContentCardTag, string> = {
  character: "bg-secondary text-secondary-foreground",
  story: "bg-secondary text-secondary-foreground",
  public: "border border-border text-muted-foreground",
  link: "border border-border text-muted-foreground",
  private: "border border-border text-muted-foreground",
  restricted: "bg-destructive/10 text-destructive",
  unpublished: "border border-border text-muted-foreground",
};

const TAG_ICON: Partial<Record<ContentCardTag, LucideIcon>> = {
  character: UserRound,
  story: BookOpen,
};

/** 카드에 얹는 지표. `viewCount` 하나만 오면 홈·즐겨찾기·프로필이 원래 쓰던 `조회수 {n}` 평문 그대로 두고,
 * 셋이 다 오면(`/my`) 라벨을 아이콘으로 바꿔 스크린리더에만 한국어 이름을 남긴다.
 *
 * 셋을 아이콘으로 바꾼 이유는 공간이 아니다 — 390px 2열(카드 내부폭 139px)에서 세 지표는 **아이콘으로 줄여도
 * 203px가 필요해 어차피 두 줄로 접힌다**(실측). 접히는 것 자체는 파손이 아니라서 그대로 두고, 아이콘을 고른
 * 진짜 이유는 어휘 일치다 — `ContentDetailView`가 이미 `Eye`/`MessageCircle`/`Heart`를 같은 뜻으로 쓴다. */
export type ContentCardMetrics = {
  viewCount: number;
  chatCount?: number;
  likeCount?: number;
};

type ContentCardProps = {
  thumbnailUrl: string | null;
  title: string;
  metrics?: ContentCardMetrics;
  /** 지표 대신(또는 지표가 없을 때) 그 자리에 놓는 한 줄. `/my`의 초안 카드가 "… 수정"을 여기 넣는다 —
   * 초안은 지표가 없어 이 줄이 없으면 제목과 배지 사이가 통째로 비고, 목록의 정렬 키(수정일)를
   * 화면에서 확인할 방법도 사라진다(US-008). */
  metaLabel?: string;
  author?: { name: string; profileUrl: string };
  tags?: ContentCardTag[];
  /** 카드 안에서 카드와 다른 동작을 하는 요소(⋯ 메뉴 등). 넣는 쪽이 click·keydown을 모두
   * `stopPropagation` 해야 한다 — 자세한 이유는 `apps/web/CLAUDE.md`의 "클릭 카드" 항목. */
  actions?: ReactNode;
  /** US-013 — 첫 화면에 보이는 카드만 lazy를 풀고 즉시 로드한다. 그리드가
   * `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라 첫 줄이 뷰포트에 따라 2/3/4장으로 갈리므로,
   * 호출부는 최대값 4를 기준으로 `index < 4`에 준다(좁은 화면에선 2장이 과하게 당겨지는 정도). */
  priority?: boolean;
  /** LCP 후보 1장(`index === 0`)에만 준다 — 여러 장에 주면 우선순위 신호가 희석돼 의미가 없다. */
  isLcpCandidate?: boolean;
  onClick: () => void;
  onAuthorClick?: () => void;
};

/** techspec-home-discovery.md §3 — 홈/즐겨찾기/프로필/내 작품 4곳이 공용으로 쓰는 카드. 카드 전체가 클릭 영역
 * (상세 모달 오픈, US-042)이며, `onAuthorClick`이 있으면 작가명만, `actions`가 있으면 그 영역만 별도 클릭
 * 영역이 된다(홈의 크리에이터 필터 US-044, 프로필의 공개범위 메뉴 US-115) — 그래서 바깥 컨테이너는
 * `<button>`이 아니라 `role="button"` `div`를 쓴다(버튼 안에 버튼을 중첩할 수 없다).
 *
 * 표면은 `bg-card`가 아니라 button-outline 레시피(`border-border bg-background` + `hover:bg-muted`)다 —
 * 이 4개 화면 전부에서 카드가 그 화면의 주 인터랙션인데, `bg-card` 위에서는 `hover:bg-accent/50`도
 * `hover:bg-muted`도 픽셀상 아무것도 그리지 않기 때문이다(다크 실측 **1.0000:1**, 라이트 1.0178:1 —
 * `--muted`/`--accent/50` 합성값이 `--card`와 같은 값이 된다). 자세한 근거는 `apps/web/CLAUDE.md`의
 * "`--muted`와 `--card`는 같은 값이다" 항목. */
export function ContentCard({
  thumbnailUrl,
  title,
  metrics,
  metaLabel,
  author,
  tags,
  actions,
  priority = false,
  isLcpCandidate = false,
  onClick,
  onAuthorClick,
}: ContentCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onClick();
      }}
      className="flex w-full cursor-pointer flex-col gap-3 rounded-xl border border-border bg-background p-3 text-left outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px motion-safe:transition-colors"
    >
      {/* 웰은 `bg-muted`가 아니라 `bg-secondary`다 — 카드의 `hover:bg-muted`가 카드 표면을 웰과 같은
          값으로 만들어, `bg-muted` 웰은 hover에서 정확히 1.0000:1로 사라진다(실측). 썸네일이 아직 없는
          초안 카드(US-007의 지연 생성이 만드는 정상 상태)에서만 보이는 자리라 그때가 곧 전부다. */}
      <div className="aspect-square overflow-hidden rounded-lg bg-secondary">
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
        <div className="flex items-center gap-1">
          <p className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{title}</p>
          {actions}
        </div>

        {metrics && <ContentCardMetricList metrics={metrics} />}

        {metaLabel && <p className="text-xs text-muted-foreground">{metaLabel}</p>}

        {author &&
          (onAuthorClick ? (
            <button
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
            <p className="truncate text-xs text-muted-foreground">{author.name}</p>
          ))}

        {tags && tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <ContentCardTagBadge key={tag} tag={tag} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ContentCardMetricList({ metrics }: { metrics: ContentCardMetrics }) {
  if (metrics.chatCount === undefined && metrics.likeCount === undefined) {
    return <p className="text-xs text-muted-foreground">조회수 {metrics.viewCount.toLocaleString()}</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground">
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
      <span className="sr-only">{label}</span>
      {value.toLocaleString()}
    </span>
  );
}

function ContentCardTagBadge({ tag }: { tag: ContentCardTag }) {
  const Icon = TAG_ICON[tag];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        TAG_CLASS[tag],
      )}
    >
      {Icon && <Icon aria-hidden className="size-3.5" />}
      {TAG_LABEL[tag]}
    </span>
  );
}
