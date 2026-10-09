import type { EnabledFeature } from "../api/sessionQueryOptions";

/** 이 계정에 기능이 열려 있는가. 세션을 아직 못 읽었거나(`undefined`) 이 필드가 없는 옛 `/me` 응답이면 닫힌 것으로
 * 본다 — 웹과 API 는 따로 배포돼, 생성 타입이 필수라고 적어도 필드가 빠진 응답이 올 수 있다. */
export function hasEnabledFeature(enabledFeatures: readonly EnabledFeature[] | undefined, feature: EnabledFeature): boolean {
  return (enabledFeatures ?? []).includes(feature);
}
