/** 미션 3종의 한국어 라벨. `CloverMissionItem.key`는 BE에서
 * `Literal`이 아니라 `string`이다(`kind`와 같은 이유 — admin `CLOVER_KIND_LABELS`
 * 선례와 같은 관례) — 그래서 여기도 `Record<string, string>`이고, 모르는 키는 호출부가
 * 원문 그대로 보여준다(`?? key` 폴백). */
export const CLOVER_MISSION_LABELS: Record<string, string> = {
  first_publish: "첫 작품 발행",
  first_message: "첫 대화",
  first_image: "첫 이미지 생성",
};
