import { STORY_FIELD_LABELS, type StoryFieldKey } from "@/features/build-story";

import type { GuideMockupContext } from "../model/guideMockupContext";
import { mediaGridDescription } from "../model/mediaGridDescription";
import { isStoryFieldKey, mockupCaption } from "../model/mockupCaption";
import { parseMockupValue } from "../model/mockupValue";
import type { FieldValue, GuideFieldBlock as GuideFieldBlockData, GuideNoteBlock } from "../model/parseManuscript";
import { GuideBadComparison } from "./GuideBadComparison";
import { GuideCardListMockup } from "./GuideCardListMockup";
import { GuideDisclosure } from "./GuideDisclosure";
import { GuideFieldMockups } from "./GuideFieldMockup";
import { GuideItems } from "./GuideItems";
import { MockupTextarea } from "./GuideMockupControls";
import { GuideMockupFrame } from "./GuideMockupFrame";

// 칸 블록 배치. 좁은 화면은 제목·설명 → 칸 그림 → 접기 줄을 위아래로 쌓고, 넓은 화면은 설명(왼쪽) ↔ 그림(오른쪽) 두 열에
// 접기 줄을 아래 전폭으로 둔다. 세 자식의 자리를 명시하는 이유: 자동 배치에 맡기면 제목과 설명이 서로 다른 열로 갈린다.
// 왼쪽 열에만 폭 상한을 두고 그림은 오른쪽 열을 끝까지 채운다 — 두 열 모두 트랙에 상한을 주면 1024~1368px 에서 남는
// 폭이 두 열로 나뉘어 그림이 줄어든다. 그림에 따로 폭 상한을 두지 않는 이유: 본문 폭이 이미 그림 폭을 정해, 상한을 두면
// 그림 오른쪽 끝만 칩 줄·이전/다음 카드의 오른쪽 끝보다 안쪽에서 멈춘다. DOM 순서가 두 폭에서 같아 낭독·Tab 순서도 같다.
const SECTION_CLASS =
  "grid scroll-mt-20 gap-3 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start lg:gap-x-10";
const TEXT_CELL_CLASS = "flex min-w-0 flex-col gap-3 lg:col-start-1 lg:row-start-1";
const MOCKUP_CELL_CLASS = "w-full lg:col-start-2 lg:row-start-1";
const DISCLOSURE_CELL_CLASS = "flex min-w-0 flex-col gap-2 lg:col-span-2 lg:row-start-2";
// 접기 칸은 넓은 화면에서 두 열 전폭이라, 산문을 그 폭대로 두면 한 줄이 100자를 넘어 읽기 어렵다. 나쁜 예 대비는 두 쪽을
// 나란히 놓아야 해 전폭을 그대로 쓰고, "자세히"의 산문만 단계 리드와 같은 읽기 폭으로 묶는다.
const DETAILS_PROSE_CLASS = "flex max-w-2xl min-w-0 flex-col gap-3";
const HEADING_CLASS = "text-lg font-semibold tracking-tight text-balance text-foreground";

type GuideFieldBlockProps = {
  block: GuideFieldBlockData;
  context: GuideMockupContext;
};

/**
 * 칸 하나(또는 한 번에 보는 칸 묶음) — 제목·짧은 설명·빌더 칸 그림·접힌 "자세히"와 "나쁜 예". 블록 id 가 첫 칸 키라
 * 개요의 칸 링크와 실수 목록 링크가 `#<칸 키>` 로 이 자리에 온다(`scroll-mt-20` 은 sticky 헤더 아래로 숨지 않게).
 *
 * 반복 카드 목록 칸에 그 카드 안 칸 값이 함께 있으면(전개 예시) 본 그림은 접힌 카드 머리 줄만 그리고, 카드 한 장을 편
 * 모습은 "자세히" 맨 앞에 둔다 — 펼친 카드를 본 그림에 두면 접힌 상태의 페이지가 그만큼 길어진다.
 */
export function GuideFieldBlock({ block, context }: GuideFieldBlockProps) {
  const [firstKey = ""] = block.keys;
  const title = block.title ?? (isStoryFieldKey(firstKey) ? STORY_FIELD_LABELS[firstKey].label : firstKey);
  const headingId = `${block.id}-title`;
  const listKey = isStoryFieldKey(firstKey) && context.mockups[firstKey].kind === "cardList" ? firstKey : null;
  const cardFieldValues = listKey ? block.values.filter((value) => value.key.startsWith(`${listKey}.*.`)) : [];
  const mainValues = block.values.filter((value) => !cardFieldValues.includes(value));
  const hasDetails = block.details !== null || cardFieldValues.length > 0;

  return (
    <section id={block.id} aria-labelledby={headingId} className={SECTION_CLASS}>
      <div className={TEXT_CELL_CLASS}>
        <h2 id={headingId} className={HEADING_CLASS}>
          {title}
        </h2>
        <GuideItems items={block.intro} />
      </div>
      <GuideMockupFrame
        caption={mockupCaption(block, context.mockups, context.mediaCellName)}
        srDescription={mediaGridSrDescription(mainValues, context)}
        className={MOCKUP_CELL_CLASS}
      >
        <GuideFieldMockups values={mainValues} context={context} />
      </GuideMockupFrame>
      {(hasDetails || block.bad.length > 0) && (
        <div className={DISCLOSURE_CELL_CLASS}>
          {hasDetails && (
            <GuideDisclosure summary="자세히" context={title}>
              {listKey && cardFieldValues.length > 0 && (
                <OpenCardMockup listKey={listKey} values={cardFieldValues} />
              )}
              {block.details && (
                <div className={DETAILS_PROSE_CLASS}>
                  <GuideItems items={block.details} />
                </div>
              )}
            </GuideDisclosure>
          )}
          {block.bad.length > 0 && (
            <GuideDisclosure summary={badSummary(block)} context={title}>
              <div className="flex flex-col gap-6">
                {block.bad.map((part) => (
                  <GuideBadComparison
                    key={part.title}
                    part={part}
                    context={context}
                    showsTitle={block.bad.length > 1}
                  />
                ))}
              </div>
            </GuideDisclosure>
          )}
        </div>
      )}
    </section>
  );
}

/** 나쁜 예가 하나면 그 이름을 접기 줄에 싣고, 여럿이면 개수만 — 이름을 다 이으면 좁은 화면에서 접기 줄이 두 줄이 된다. */
function badSummary(block: GuideFieldBlockData): string {
  const [only] = block.bad;
  return block.bad.length === 1 && only ? `나쁜 예 · ${only.title}` : `나쁜 예 ${block.bad.length}가지`;
}

function mediaGridSrDescription(values: readonly FieldValue[], context: GuideMockupContext): string | undefined {
  const grid = values.find((value) => value.key === "mediaBook.cells");
  if (!grid) return undefined;
  const parsed = parseMockupValue("mediaGrid", grid.body);
  const people = parseMockupValue("chips", context.valueOf("mediaBook.people") ?? "[]");
  const scenes = parseMockupValue("chips", context.valueOf("mediaBook.scenes") ?? "[]");
  if (parsed.kind !== "mediaGrid" || people.kind !== "chips" || scenes.kind !== "chips") return undefined;
  return mediaGridDescription({ people: people.items, scenes: scenes.items, cells: parsed.cells, selected: parsed.selected });
}

type OpenCardMockupProps = {
  listKey: StoryFieldKey;
  values: readonly FieldValue[];
};

/**
 * 카드 한 장을 편 모습. 빌더에서 이 칸들의 이름("사용자 메시지" 등)은 라벨이 아니라 빈 칸의 자리표시라 값이 찬 칸에는
 * 보이지 않는다 — 그래서 칸 위에 라벨을 그리지 않고, 위에서부터 어느 칸인지는 캡션이 말한다.
 */
function OpenCardMockup({ listKey, values }: OpenCardMockupProps) {
  const fieldLabels = values.map((value) => (isStoryFieldKey(value.key) ? STORY_FIELD_LABELS[value.key].label : value.key));
  const card = Object.fromEntries(values.map((value) => [value.key.slice(`${listKey}.*.`.length), value.body]));
  return (
    <GuideMockupFrame caption={`${STORY_FIELD_LABELS[listKey].label} 1 펼친 모습 · 위부터 ${fieldLabels.join(", ")}`}>
      <GuideCardListMockup listKey={listKey} cards={[card]} more={0}>
        {values.map((value) => (
          <MockupTextarea key={value.key} text={value.body} />
        ))}
      </GuideCardListMockup>
    </GuideMockupFrame>
  );
}

type GuideNoteBlockViewProps = {
  block: GuideNoteBlock;
};

/** 칸에 붙지 않는 사실(게이지와 상태창, 글 속 표기 등) — 칸 블록과 같은 자리 배치에서 그림만 없다. */
export function GuideNoteBlockView({ block }: GuideNoteBlockViewProps) {
  const headingId = `${block.id}-title`;
  return (
    <section id={block.id} aria-labelledby={headingId} className={SECTION_CLASS}>
      <div className={TEXT_CELL_CLASS}>
        <h2 id={headingId} className={HEADING_CLASS}>
          {block.title}
        </h2>
        <GuideItems items={block.intro} />
      </div>
      {block.details && (
        <div className={DISCLOSURE_CELL_CLASS}>
          <GuideDisclosure summary="자세히" context={block.title}>
            <div className={DETAILS_PROSE_CLASS}>
              <GuideItems items={block.details} />
            </div>
          </GuideDisclosure>
        </div>
      )}
    </section>
  );
}
