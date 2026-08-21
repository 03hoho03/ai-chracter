import { Link } from "@tanstack/react-router";
import { BookOpen, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ContentType } from "@/entities/content";

import { NEW_DRAFT_SEGMENT } from "../config/newDraftSegment";

type BuilderTypeOption = {
  type: ContentType;
  label: string;
  /** 무엇을 만드는지. */
  summary: string;
  /** 완성 후 어디에 노출되는지. */
  exposure: string;
  Icon: LucideIcon;
};

const BUILDER_TYPE_OPTIONS: BuilderTypeOption[] = [
  {
    type: "character",
    label: "캐릭터",
    summary: "성격과 말투를 정해 대화 상대를 만들어요.",
    exposure: "발행하면 홈 캐릭터 목록에 올라가요.",
    Icon: UserRound,
  },
  {
    type: "story",
    label: "스토리",
    summary: "인물과 전개를 짜서 이야기를 만들어요.",
    exposure: "발행하면 홈 스토리 목록에 올라가요.",
    Icon: BookOpen,
  },
];

/** prd-creator-entry-and-my-works.md US-006 — 만들기 진입점이 닿는 첫 화면. 캐릭터/스토리 중 하나를 골라
 * 각 빌더로 들어간다. 카드는 `<Link>`라 새 탭 열기·가운데 클릭이 그대로 동작한다(버튼 + navigate가 아니라). */
export function BuilderTypeSelectPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">작품 만들기</h1>

      {/* 2열 전환이 `sm`(640px)이 아니라 `md`(768px)인 건 실측이다 — 640px에서 2열은 카드를 290px로 만들어
          텍스트 폭이 224px가 되는데, 가장 긴 설명 줄이 227px라 640~645px 구간에서만 한 줄이 접힌다. */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {BUILDER_TYPE_OPTIONS.map((option) => (
          <BuilderTypeCard key={option.type} option={option} />
        ))}
      </div>
    </main>
  );
}

// 카드 배경은 `bg-card`가 아니라 DESIGN.md의 button-outline 레시피(`background` + hover `muted`)를 카드 크기로
// 쓴다 — 이 두 카드가 화면의 전부라 hover가 안 보이면 화면이 죽는데, `bg-card` 위에서는 정규 카드 hover가
// 아무것도 하지 않는다. `hover:bg-accent/50`은 `bg-card`를 덮어쓰고 **부모(페이지 배경) 위에** 합성되므로
// 다크에서 0.5×0.26 + 0.5×0.16 ≈ 0.21 = `card`와 같은 값이 된다(픽셀 실측 다크 1.0000:1 / 라이트 1.0178:1).
// `hover:bg-secondary`는 보이긴 하지만 라이트에서 설명 문구(`muted-foreground`)가 4.29:1로 AA에 미달한다
// (DESIGN.md가 이름을 대서 금지한 조합). 남은 선택지가 outline 레시피다.
//
// 아이콘에 `bg-muted`/`bg-secondary` 웰을 씌우지 않는다 — 여기 아이콘은 썸네일 자리가 아니라 장식이라
// 웰이 담을 것이 없고(`DraftCard`의 웰은 이미지 슬롯이다), 웰이 먹는 52px가 설명 두 줄을 좁은 폭에서 접히게 한다.
function BuilderTypeCard({ option }: { option: BuilderTypeOption }) {
  return (
    <Link
      to="/builder/$type/$draftId"
      params={{ type: option.type, draftId: NEW_DRAFT_SEGMENT }}
      className="flex items-start gap-3 rounded-xl border border-border bg-background p-4 outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
    >
      <option.Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
      <span className="flex min-w-0 flex-col gap-1 break-keep">
        <span className="text-base font-semibold text-foreground">{option.label}</span>
        <span className="text-sm text-muted-foreground">{option.summary}</span>
        <span className="text-sm text-muted-foreground">{option.exposure}</span>
      </span>
    </Link>
  );
}
