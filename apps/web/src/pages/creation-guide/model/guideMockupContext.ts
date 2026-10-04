import type { StoryFieldMockups } from "../config/storyFieldMockups";
import { selectedMediaCellName } from "./mockupCaption";
import type { GuideStep } from "./toGuidePages";

/** 목업이 칸 값 밖에서 알아야 하는 것. */
export type GuideMockupContext = {
  mockups: StoryFieldMockups;
  /** 미디어 북 칸 상세 블록 캡션의 칸 이름(`유나 / 리딩`). */
  mediaCellName: string | null;
  /** 칸 키의 원고 목업 값. 배치표가 같은 단계의 인물·장면 값에서 이름을 읽고, 개요가 예시 작품 이름·한줄소개를 읽는다. */
  valueOf: (key: string) => string | undefined;
};

/** 칸 블록 본 값(나쁜 예 값은 빼고)을 칸 키로 모은다. 한 칸 키는 한 블록에만 나온다(`toGuidePages` 가 확인한다). */
export function toGuideMockupContext(steps: readonly GuideStep[], mockups: StoryFieldMockups): GuideMockupContext {
  const values = new Map(
    steps.flatMap((step) =>
      step.content.flatMap((item) =>
        item.kind === "field" ? item.values.map((value) => [value.key, value.body] as const) : [],
      ),
    ),
  );
  return { mockups, mediaCellName: selectedMediaCellName(steps), valueOf: (key) => values.get(key) };
}
