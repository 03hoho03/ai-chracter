import { useMemo } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import type { PromptChannel } from "../model/channels";
import type { PromptSetFormValues } from "../model/schema";
import { SectionRow } from "./SectionRow";

type ChannelSectionListProps = {
  channel: PromptChannel;
};

type SortedSection = {
  fieldIndex: number;
  order: number;
};

/** 같은 슬롯의 variant끼리(예: `template_instruction`의 4종), 또는 scope로만 갈리는 짝
 * (`self_definition`의 스토리/캐릭터)은 서로 `order`가 같다 — 한쪽만 실제로 렌더되는 상호
 * 배타 관계라 둘 사이의 상대 순서엔 의미가 없기 때문이다(§4-2). 이 동률 두 행끼리
 * `order`를 맞바꾸면 값이 같아 아무 일도 안 일어나므로, 값이 실제로 다른 가장 가까운
 * 이웃을 찾아 그 이웃과 맞바꾼다 — 동률 블록을 한 번에 건너뛰는 것과 같다. */
function findDistinctOrderNeighbor<T extends SortedSection>(
  sorted: T[],
  fromPosition: number,
  currentOrder: number,
  direction: 1 | -1,
): T | undefined {
  let index = fromPosition + direction;
  while (index >= 0 && index < sorted.length) {
    const candidate = sorted[index];
    if (candidate && candidate.order !== currentOrder) return candidate;
    index += direction;
  }
  return undefined;
}

/** 채널 하나의 섹션 목록 — `order` 오름차순(동률이면 slot·variant)으로 보여준다. 백엔드
 * `_sections_of`가 조립 직전에 `(channel, order, slot, variant)`로 정렬하는 것과 같은 기준이라,
 * 여기 보이는 순서가 곧 실제로 이어붙는 순서다.
 *
 * 위/아래 버튼은 배열 위치가 아니라 `order` 값을 맞바꾼다 — `order`만이 서버가 보는 값이고
 * (§4-2), 필드 배열 위치 자체는 의미가 없다. 동률인 이웃은 건너뛴다(`findDistinctOrderNeighbor`).
 * 정렬에 쓰는 `order`는
 * `useWatch`로 그 필드들만 구독한다 — body를 고치는 키 입력마다 48행 전체가 다시 정렬되는
 * 것을 막기 위해서다(body는 `register`로 각자 구독하므로 여기 영향이 없다). */
export function ChannelSectionList({ channel }: ChannelSectionListProps) {
  const { control, getValues, setValue } = useFormContext<PromptSetFormValues>();
  const allSections = getValues("sections");

  const channelFieldIndexes = allSections
    .map((section, index) => ({ ...section, fieldIndex: index }))
    .filter((section) => section.channel === channel);

  // 매 렌더 새 배열을 만들어 그대로 넘기면 `useWatch`가 매번 재구독한다 — 필드 인덱스
  // 집합(=이 채널의 섹션 구성) 자체는 저장/복원으로 폼 전체가 리셋될 때만 바뀌므로 그
  // 경우에만 새 배열을 만든다.
  const fieldIndexKey = channelFieldIndexes.map((section) => section.fieldIndex).join(",");
  const orderPaths = useMemo(
    () => channelFieldIndexes.map((section) => `sections.${section.fieldIndex}.order` as const),
    [fieldIndexKey],
  );
  const liveOrders = useWatch({ control, name: orderPaths });

  const sorted = channelFieldIndexes
    .map((section, position) => ({ ...section, order: liveOrders[position] ?? section.order }))
    .sort((a, b) => a.order - b.order || a.slot.localeCompare(b.slot) || a.variant.localeCompare(b.variant));

  function swapOrder(fieldIndexA: number, fieldIndexB: number) {
    const orderA = getValues(`sections.${fieldIndexA}.order`);
    const orderB = getValues(`sections.${fieldIndexB}.order`);
    setValue(`sections.${fieldIndexA}.order`, orderB, { shouldDirty: true });
    setValue(`sections.${fieldIndexB}.order`, orderA, { shouldDirty: true });
  }

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((section, position) => {
        const previous = findDistinctOrderNeighbor(sorted, position, section.order, -1);
        const next = findDistinctOrderNeighbor(sorted, position, section.order, 1);

        return (
          <SectionRow
            key={`${section.channel}:${section.scope}:${section.slot}:${section.variant}`}
            fieldKey={`${section.channel}-${section.scope}-${section.slot}-${section.variant}`}
            fieldIndex={section.fieldIndex}
            channel={section.channel}
            scope={section.scope}
            slot={section.slot}
            variant={section.variant}
            conditional={section.conditional}
            canMoveUp={previous !== undefined}
            canMoveDown={next !== undefined}
            onMoveUp={() => previous && swapOrder(section.fieldIndex, previous.fieldIndex)}
            onMoveDown={() => next && swapOrder(section.fieldIndex, next.fieldIndex)}
          />
        );
      })}
    </div>
  );
}
