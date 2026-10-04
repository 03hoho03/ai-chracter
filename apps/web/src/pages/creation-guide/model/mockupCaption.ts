import { STORY_FIELD_LABELS, type StoryFieldKey } from "@/features/build-story";

import { READ_TIMING_GROUPS, type ReadTimingId, type StoryFieldMockups } from "../config/storyFieldMockups";
import { parseMockupValue } from "./mockupValue";
import type { GuideFieldBlock } from "./parseManuscript";
import type { GuideStep } from "./toGuidePages";

/** 미디어 북 칸 상세 블록이 가리키는 칸의 이름(`유나 / 리딩`). 배치표 값의 고른 칸에서 만든다. */
const MEDIA_CELL_KEY_PREFIX = "mediaBook.cells.*.";

/**
 * 칸 블록 목업의 캡션 한 줄 — `<위치> · <AI가 읽는 때>`. 위치는 키에서 만든다: 반복 카드 안 칸이면 `<목록 라벨> 카드 안`,
 * 미디어 북 칸 상세면 `<인물> / <장면> 칸`, 그 밖은 `예시 작품 입력`. 읽는 때는 블록 키들의 표 값(블록당 한 종류)이고
 * 없으면 뺀다. 캡션 글자를 원고에 따로 쓰지 않는 것은 칸 키·라벨·읽는 때 표에서 만들 수 있는 글이라서다.
 */
export function mockupCaption(
  block: Pick<GuideFieldBlock, "keys">,
  mockups: StoryFieldMockups,
  mediaCellName: string | null,
): string {
  const [firstKey] = block.keys;
  const timing = blockReadTiming(block, mockups);
  const caption = READ_TIMING_GROUPS.find((group) => group.id === timing)?.caption;
  return [positionOf(firstKey ?? "", mediaCellName), caption].filter(Boolean).join(" · ");
}

/** 블록 키 가운데 AI가 읽는 때가 정해진 키들의 값. 둘 이상 섞이면 캡션 하나로 말할 수 없어 던진다. */
export function blockReadTiming(block: Pick<GuideFieldBlock, "keys">, mockups: StoryFieldMockups): ReadTimingId | null {
  const timings = new Set(
    block.keys.flatMap((key) => {
      const timing = isStoryFieldKey(key) ? mockups[key].readTiming : null;
      return timing ? [timing] : [];
    }),
  );
  if (timings.size > 1) throw new Error(`한 블록에 AI가 읽는 때가 둘 이상이다: ${block.keys.join(", ")}`);
  return [...timings][0] ?? null;
}

function positionOf(key: string, mediaCellName: string | null): string {
  if (key.startsWith(MEDIA_CELL_KEY_PREFIX) && mediaCellName) return `${mediaCellName} 칸`;
  const lastStar = key.lastIndexOf(".*");
  if (lastStar === -1) return "예시 작품 입력";
  const listKey = key.slice(0, lastStar);
  return isStoryFieldKey(listKey) ? `${STORY_FIELD_LABELS[listKey].label} 카드 안` : "예시 작품 입력";
}

/**
 * 미디어 북 단계의 배치표 값에서 고른 칸의 이름(`유나 / 리딩`)을 만든다. 인물·장면 이름은 같은 단계의 인물·장면 칸
 * 값에서 읽는다 — 배치표 값에는 위치 번호만 있어 이름 사본이 생기지 않는다. 미디어 북 블록이 없으면 null.
 */
export function selectedMediaCellName(steps: readonly GuideStep[]): string | null {
  const values = new Map(
    steps.flatMap((step) =>
      step.content.flatMap((item) => (item.kind === "field" ? item.values.map((value) => [value.key, value.body] as const) : [])),
    ),
  );
  const people = values.get("mediaBook.people");
  const scenes = values.get("mediaBook.scenes");
  const grid = values.get("mediaBook.cells");
  if (people === undefined || scenes === undefined || grid === undefined) return null;

  const peopleValue = parseMockupValue("chips", people);
  const scenesValue = parseMockupValue("chips", scenes);
  const gridValue = parseMockupValue("mediaGrid", grid);
  if (peopleValue.kind !== "chips" || scenesValue.kind !== "chips" || gridValue.kind !== "mediaGrid") return null;
  const person = peopleValue.items[gridValue.selected.person];
  const scene = scenesValue.items[gridValue.selected.scene];
  if (person === undefined || scene === undefined) throw new Error("배치표의 고른 칸이 인물·장면 목록 밖이다");
  return `${person} / ${scene}`;
}

export function isStoryFieldKey(key: string): key is StoryFieldKey {
  return Object.hasOwn(STORY_FIELD_LABELS, key);
}
