import { cn } from "@ai-character-chat/ui/lib/utils";
import { useFormContext, useWatch, type FieldValues } from "react-hook-form";

import { ContentCard, toThumbnailAspect, useContentListQuery } from "@/entities/content";
import type { ContentCardProps, ContentType } from "@/entities/content";
import type { PreviewStartPayload } from "@/entities/preview-session";
import { useSessionQuery } from "@/entities/session";
import { PreviewCloseHeader, PreviewSessionView } from "@/widgets/preview-session";

export type BuilderPreviewProps<TFieldValues extends FieldValues> = {
  /** 활성 탭(`TABS[activeTab].preview`)에서 파생된 값 — Shell이 계산해 넘긴다(A-6, 상세 프리뷰는
   * 범위 밖이라 카드·대화 2종뿐이다). */
  kind: "card" | "chat";
  getPayload: () => PreviewStartPayload;
  /** Shell은 lg 이상에서도 항상 이 콜백을 넘긴다 — 분기는 값의 유무가 아니라 CSS다.
   * `PreviewCloseHeader`가 닫기 버튼 자체를 `lg:hidden`으로 숨기므로 lg 이상에서는 트리에 있어도
   * 화면에 없고, lg 미만 전체화면 모드에서만 실제로 보인다(T-6, JS `useMedia` 아님). */
  onClose?: () => void;
  /** `kind === "card"`에서만 쓰인다. `useContentListQuery`가 배경 목록을 가져올 콘텐츠 타입. */
  contentType: ContentType;
  /** `kind === "card"`에서만 쓰인다. 초안 응답의 표시 전용 썸네일 URL(builder-techspec.md §7) —
   * 폼 값엔 `{assetId}`뿐이라 URL은 항상 인자로 받는다. */
  thumbnailUrl: string | null;
  /** `kind === "card"`에서만 쓰인다. `features/build-story`·`features/build-character`가 이미
   * 만들어 둔 순수 변환 함수를 그대로 주입받는다 — 이 위젯은 스토리/캐릭터를 구분하지 않는다. */
  formToCard: (
    values: TFieldValues,
    ctx: { thumbnailUrl: string | null; authorNickname: string },
  ) => ContentCardProps;
};

/** 배경으로 까는 목록 카드 최대 개수. 내 카드(1장) + 7장 = 8장 — 이 앱의 그리드 스켈레톤들
 * (`ContentCardSkeleton` 등)이 이미 쓰는 "4열 기준 2행" 관례와 맞췄다. 목록이 이보다 적게 오면
 * 그만큼만 그린다 — 개수를 채우는 건 이 위젯의 책임이 아니다(D-8, 배경은 맥락일 뿐이다). */
const BACKGROUND_CARD_LIMIT = 7;

/**
 * builder-techspec.md §6(T-3) — 빌더 2단 레이아웃의 우측 프리뷰 패널. `BuilderPage`가 `renderPreview`
 * 콜백에 이 컴포넌트를 주입한다 — Shell은 이 위젯을 직접 import하지 않는다(techspec §2, 주입 방식은
 * 그대로 유지).
 *
 * 제네릭인 이유: `kind === "card"`일 때 폼 값을 구독하려면 이 컴포넌트가 Shell의 `FormProvider` 트리
 * 안에서 `useFormContext()`를 불러야 하는데(`renderPreview`의 반환값이 Shell 렌더 결과 안에 꽂히므로
 * 가능하다), 스토리·캐릭터 두 폼 타입을 하나의 위젯이 같이 다루려면 타입 매개변수가 필요하다.
 */
export function BuilderPreview<TFieldValues extends FieldValues>({
  kind,
  getPayload,
  onClose,
  contentType,
  thumbnailUrl,
  formToCard,
}: BuilderPreviewProps<TFieldValues>) {
  // builder-progress.md 6단계 리뷰 발견 1 — `kind`에 따라 다른 컴포넌트 타입을 반환하면(과거엔
  // `if (kind === "chat") return <PreviewSessionView/>`) 카드↔대화 탭 경계를 넘을 때마다 React가
  // 둘 다 언마운트/리마운트한다 — 진행 중이던 대화가 화면에서 사라지고 세션도 중복 생성됐다. 대신
  // 카드·대화를 항상 함께 마운트하고 안 보이는 쪽만 `hidden`으로 접어 리마운트 자체를 없앤다.
  // D-7(지연 시작, builder-techspec.md §6-2)이 있어야 이 상시 마운트가 공짜다 — 첫 전송 전에는
  // 대화 쪽이 마운트돼 있어도 세션이 생기지 않는다.
  return (
    <>
      <div className={cn(kind === "chat" ? undefined : "hidden")}>
        <PreviewSessionView getPayload={getPayload} onClose={onClose} />
      </div>
      <div className={cn(kind === "card" ? undefined : "hidden")}>
        <CardPreview
          contentType={contentType}
          thumbnailUrl={thumbnailUrl}
          formToCard={formToCard}
          onClose={onClose}
        />
      </div>
    </>
  );
}

type CardPreviewProps<TFieldValues extends FieldValues> = Pick<
  BuilderPreviewProps<TFieldValues>,
  "contentType" | "thumbnailUrl" | "formToCard" | "onClose"
>;

function CardPreview<TFieldValues extends FieldValues>({
  contentType,
  thumbnailUrl,
  formToCard,
  onClose,
}: CardPreviewProps<TFieldValues>) {
  const { control, getValues } = useFormContext<TFieldValues>();
  // 폼 아무 필드나 바뀌면 재렌더되도록 구독만 한다 — 반환값은 쓰지 않는다. `useWatch({control})`의
  // 반환 타입은 `DeepPartialSkipArrayKey<TFieldValues>`라 `formToCard`가 요구하는 전체 타입과 안
  // 맞고, `name`으로 `profile`만 좁히려 해도 이 컴포넌트는 스토리·캐릭터 공용이라 제네릭
  // `TFieldValues`에서 "profile"이 유효한 경로임을 타입 수준에서 증명할 수 없다. 그래서 신호로만
  // 쓰고 실제 값은 항상 완전한 타입을 주는 `getValues()`로 읽는다 — `useAutosave`가 쓰는 "watch로
  // 신호, 값은 getValues" 관례(`apps/web/CLAUDE.md`)와 같다. `formToCard`는 zod `safeParse`가 아니라
  // 필드 몇 개를 그대로 옮기는 값싼 호출이라(3단계에서 지운 `canPublish`의 `safeParse`와 다르다) 전체
  // 폼을 구독해도 매 렌더 재계산 비용은 무시할 만하다.
  useWatch({ control });
  const values = getValues();

  const sessionQuery = useSessionQuery();
  const myCard = formToCard(values, {
    thumbnailUrl,
    authorNickname: sessionQuery.data?.nickname ?? "",
  });

  // 홈(`HomePage`)과 쿼리 키(`contentKeys.browse({type, sort})`)를 공유한다 — `undefined` 필터
  // 키가 직렬화에서 탈락해 해시가 같아진다. 단 **`type`이 같을 때만** 실제로 캐시가 재사용된다.
  // 홈의 `type`은 전역 토글 atom(기본값 `story`)이라, 예를 들어 캐릭터 빌더를 열었는데 홈이 스토리
  // 탭에 있으면 캐시가 갈려 새 요청이 나간다(builder-progress.md §0-3).
  const listQuery = useContentListQuery({ type: contentType, sort: "latest" });
  const backgroundItems = listQuery.data?.pages[0]?.items.slice(0, BACKGROUND_CARD_LIMIT) ?? [];

  return (
    // builder-progress.md 6단계 리뷰 발견 2 — `h-full`은 lg 미만에서 조상에 확정 높이가 없어(그
    // 폭에서는 `BuilderLayout`이 `lg:h-[...]`만 준다) 동작하지 않았고, 카드 그리드가 페이지 전체를
    // 늘려 닫기 버튼이 스크롤 밖으로 사라졌다. `PreviewSessionView`가 쓰는 패턴대로 조상에 기대지
    // 않고 자기 높이를 직접 확정한다.
    <div className="flex h-below-header flex-col">
      <PreviewCloseHeader onClose={onClose} />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 sm:px-6 py-4">
        {/* 목록 로딩·실패·빈 응답이어도 내 카드는 반드시 그린다(D-8) — 프리뷰의 주인공은 내 카드이고
            둘러싼 카드는 맥락일 뿐이다. 그래서 목록 상태에 대한 별도 에러/빈 상태 분기를 두지 않고
            `backgroundItems`가 빈 배열로 조용히 접히게 둔다. */}
        {/* `entities/content`의 `ContentCardGrid`(card-grid-techspec.md T-4, `sm:`/`md:` 뷰포트
            브레이크포인트)를 여기서는 쓰지 않는다 — 이 그리드는 폭 전체가 아니라 `BuilderLayout`의
            2단 그리드가 남긴 프리뷰 열(`1fr`) 안에 있어서, 뷰포트가 아무리 넓어도 열 자체는 좁을 수
            있다(1024~1150px 실측: 열 폭
            300~350px인데 뷰포트 기준으론 이미 `md:grid-cols-4`가 걸려 카드가 78px까지 눌리고 배지
            글자가 세로로 깨졌다). `ContentCardGrid`를 이 사례에 맞게 고치면 뷰포트 전체 폭에서 쓰는
            홈·즐겨찾기·프로필·내작품 쪽 계약이 깨지므로 손대지 않는다(A-5) — 대신 이 열 전용으로
            `grid-template-columns: repeat(auto-fit, minmax(...))`를 쓴다. 열의 **실제 렌더 폭**만 보고
            열 개수를 정하는 순수 CSS 공식이라 미디어/컨테이너 쿼리의 이산 구간(테스트 안 한 폭에서
            깨질 여지)이 없다. 하한 120px는 실측 이분탐색 근거다 — "스토리" 배지 한 개가 실제로 두 줄로
            깨지는 경계는 88~90px(그 아래 82~88px 전부 재현, 90px부터 한 줄)이라 120px는 그 위 30px
            여유를 둔 값이다. */}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-3">
          <ContentCard key="preview-own-card" {...myCard} />
          {backgroundItems.map((item) => (
            <ContentCard
              key={item.id}
              thumbnailUrl={item.thumbnailUrl ?? undefined}
              thumbnailAspect={toThumbnailAspect(contentType)}
              title={item.name}
              metrics={{ viewCount: item.viewCount }}
              author={{ name: item.creatorNickname, profileUrl: `/profile/${item.creatorUserId}` }}
              onClick={() => {}}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
