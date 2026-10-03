import type { MediaGridCell, MediaGridPosition } from "./mockupValue";

export type MediaGridMockupValue = {
  people: readonly string[];
  scenes: readonly string[];
  cells: readonly MediaGridCell[];
  selected: MediaGridPosition;
};

/** 배치표 그림을 낭독기에 한 문장으로. 그림과 같은 데이터에서 만들어 둘이 어긋날 수 없다. */
export function mediaGridDescription({ people, scenes, cells, selected }: MediaGridMockupValue): string {
  const nameOf = (position: MediaGridPosition) => `${people[position.person] ?? ""}/${scenes[position.scene] ?? ""}`;
  const hidden = cells.filter((cell) => cell.isHiddenInChat).map(nameOf);
  return [
    `인물 ${people.length}명과 장면 ${scenes.length}개를 교차한 표.`,
    `${people.length * scenes.length}칸 중 ${cells.length}칸에 그림이 있고,`,
    hidden.length > 0 ? `${hidden.join(", ")} 칸은 대화 중 띄우지 않음,` : null,
    `${nameOf(selected)} 칸을 고른 상태.`,
  ]
    .filter(Boolean)
    .join(" ");
}
