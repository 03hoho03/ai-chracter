import type { EnabledFeature } from "@/entities/session";

import { CHAT_MODEL_FEATURE_GATE, isFeatureItemVisible } from "./visibleMoreItems";

/** 채팅 모델 칩에 쓸 이름. 칩을 그리지 않을 때는 undefined 다.
 *
 * 그리지 않는 경우는 셋이다 — 이 계정에 모델 선택 기능이 꺼져 있을 때(⋮ 패널의 「AI 모델」과 같은 판정이라 둘 다
 * 사라진다), 이용제한 방일 때(입력 바가 안내로 바뀌는 방이라 상태 표시가 쓸모없다), 방 응답에 이름이 없을 때. 마지막은 이름 칸이 생기기 전의 서버라
 * 기본 모델 이름으로 채우지 않는다 — 상위 모델 방에 기본 모델 이름이 붙는 거짓이 된다. */
export function chatModelChipName({
  enabledFeatures,
  isRestricted,
  modelName,
}: {
  enabledFeatures: readonly EnabledFeature[];
  isRestricted: boolean;
  modelName: string | undefined;
}): string | undefined {
  if (!isFeatureItemVisible(CHAT_MODEL_FEATURE_GATE, enabledFeatures) || isRestricted) return undefined;
  return modelName || undefined;
}
