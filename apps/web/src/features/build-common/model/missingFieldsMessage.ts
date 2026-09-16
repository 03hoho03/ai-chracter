/** 라벨을 찾지 못한 키를 대신하는 문구 — 서버가 주는 인덱스 경로(`startingSetups[0].prologue`)나
 * 라벨이 없는 폼 경로가 영문 원문 그대로 사용자에게 새지 않게 한다
 * (builder-publish-goal-prompt.md BP-4). 두 경로가 말하는 것이 달라 fallback도 갈린다 — 아래 참조. */
const OTHER_MISSING_FIELDS_LABEL = "그 밖의 필수 항목";
const OTHER_INVALID_FIELDS_LABEL = "그 밖의 항목";

/** 키를 라벨로 옮기고(중복 제거, 인자 순서 유지) 라벨이 없는 키는 `fallbackLabel` 하나로 접는다.
 * 두 문구가 이 수집을 공유한다(builder-publish-goal-prompt.md BP-3). */
function toLabels(
  keys: readonly string[],
  labelByKey: Readonly<Record<string, string | undefined>>,
  fallbackLabel: string,
): string[] {
  const labels: string[] = [];
  let hasUnlabeled = false;
  for (const key of keys) {
    const label = labelByKey[key];
    if (label === undefined) {
      hasUnlabeled = true;
      continue;
    }
    if (!labels.includes(label)) labels.push(label);
  }
  if (hasUnlabeled || labels.length === 0) labels.push(fallbackLabel);

  return labels;
}

/**
 * 서버 400(`missingFields`) 경로의 안내 문구. 그 응답이 주는 건 **진짜 누락 목록**이라 할 일이
 * "입력"으로 확정된다. 순수 함수.
 *
 * `keys`는 서버 필드명(`genreId`)이고 라벨 맵은 **인자로 받는다** — 셸마다 필드 집합이 다르고
 * build-common은 build-story/build-character를 import할 수 없다(FSD-04).
 */
export function missingFieldsMessage(
  keys: readonly string[],
  labelByKey: Readonly<Record<string, string | undefined>>,
): string {
  const labels = toLabels(keys, labelByKey, OTHER_MISSING_FIELDS_LABEL);

  return `발행하려면 다음 항목을 입력해주세요: ${labels.join(", ")}`;
}

/**
 * 클라 검증 실패(zodResolver 에러) 경로의 안내 문구 — 문장 템플릿은 이 파일이 서버 경로 것과 함께
 * 소유한다(builder-publish-goal-prompt.md BP-3). 순수 함수.
 *
 * **"입력해주세요"라고 하지 않는다** — 이 경로에는 누락이 아닌 위반도 온다(시작설정 `.max(4)`처럼
 * 할 일이 삭제인 것). 정확한 문장은 그 필드의 인라인 에러에 있고, 토스트는 어디를 볼지만 가리킨다.
 * 같은 이유로 라벨 없는 키의 fallback에서도 "필수"를 뺀다.
 *
 * `keys`는 서버 필드명이 아니라 폼 경로(`registration.genre`)다 — `fieldLabelByFormPath`로 파생시킨
 * 맵을 넘긴다.
 */
export function invalidFieldsMessage(
  keys: readonly string[],
  labelByKey: Readonly<Record<string, string | undefined>>,
): string {
  const labels = toLabels(keys, labelByKey, OTHER_INVALID_FIELDS_LABEL);

  return `발행하려면 다음 항목을 확인해주세요: ${labels.join(", ")}`;
}

/**
 * 서버 필드명을 키로 하는 두 맵(`폼 경로`·`라벨`)에서 **"폼 경로 → 라벨"을 파생**시킨다 — 클라 검증
 * 실패 경로가 들고 있는 건 서버 필드명이 아니라 폼 경로라서다. 세 번째 맵을 손으로 적지 않기 위한
 * 것이고(builder-publish-goal-prompt.md BP-3), 그래서 라벨을 고칠 자리는 계속 한 곳이다. 순수 함수.
 */
export function fieldLabelByFormPath(
  formPathByField: Readonly<Record<string, string | undefined>>,
  labelByField: Readonly<Record<string, string | undefined>>,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [field, formPath] of Object.entries(formPathByField)) {
    const label = labelByField[field];
    if (formPath !== undefined && label !== undefined) result[formPath] = label;
  }
  return result;
}
