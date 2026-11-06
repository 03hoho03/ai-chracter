/** 확인 호출 뒤 그 항목의 버튼을 잠그는 시간(초). 서버의 항목별 확인 레이트리밋 창과 같은 값을 다시 적는다 — 응답에 그 값이 없어
 * 피할 수 없고, 어긋나도 화면이 덜·더 잠글 뿐 최종 판정은 서버의 429 다. */
export const CHECK_COOLDOWN_SECONDS = 60;

/** 확인 호출 한 번이 실제로 부르는 모델 수. 서버는 같은 id 를 쓰는 축을 한 번만 부른다. */
export function checkCallCount(modelIds: Readonly<Record<string, string>>): number {
  return new Set(Object.values(modelIds)).size;
}
