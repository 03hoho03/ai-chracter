import type { UseFormReturn } from "react-hook-form";

import type { StoryBuilderFormValues } from "@/features/build-story";

type StatPath = `startingSetups.${number}.stats.${number}`;

type StatRangeForm = Pick<UseFormReturn<StoryBuilderFormValues>, "trigger" | "getFieldState">;

/** 범위 검사가 서로 엮인 세 칸. 최소·최대 중 하나를 고치면 초기값 오류가 생기거나 풀리므로 늘 셋을 함께 본다. */
function statRangeFieldNames(statPath: StatPath) {
  return [`${statPath}.min`, `${statPath}.max`, `${statPath}.initial`] as const;
}

/**
 * 스탯 하나의 범위 세 칸만 다시 검사해 그 칸들의 오류를 붙이거나 지운다.
 *
 * 폼은 발행 전까지 검증하지 않는다(RHF 기본 모드). 그 사이 범위 모순을 칸에서 바로 알리려고 이 세 칸만 따로 검사한다.
 * `trigger` 는 리졸버로 폼 전체를 검사하지만 오류는 넘긴 이름에만 쓰고 지운다 — 다른 칸·다른 스탯의 오류는 생기지도
 * 지워지지도 않는다. 값을 바꾸지 않으므로 자동저장(값 변화 구독)도 돌지 않는다.
 */
export function revalidateStatRange(form: StatRangeForm, statPath: StatPath): Promise<boolean> {
  return form.trigger([...statRangeFieldNames(statPath)]);
}

/** 세 칸 중 하나에 오류가 떠 있을 때만 다시 검사한다 — 입력 중에는 이미 알린 오류가 고치는 즉시 풀리게 하고, 오류가
 * 없던 칸에는 다 입력하기 전(칸을 떠나기 전)에 새 오류를 띄우지 않는다. */
export function revalidateStatRangeIfInvalid(form: StatRangeForm, statPath: StatPath): Promise<boolean> | undefined {
  const names = statRangeFieldNames(statPath);
  if (!names.some((name) => form.getFieldState(name).error)) return undefined;
  return form.trigger([...names]);
}
