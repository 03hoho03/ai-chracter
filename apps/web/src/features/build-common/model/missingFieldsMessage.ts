/** 라벨을 찾지 못한 키를 대신하는 문구 — 서버가 주는 키가 영문 원문 그대로 사용자에게 새지 않게 한다. */
const OTHER_MISSING_FIELDS_LABEL = "그 밖의 필수 항목";

/** 키를 라벨로 옮기고(중복 제거, 인자 순서 유지) 라벨이 없는 키는 `fallbackLabel` 하나로 접는다. */
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
 * 서버 400(`missingFields`) 가운데 빌더가 칸으로 옮길 수 없는 키의 안내 문구. 알려진 키는 모두 칸에 걸려 폼 열 맨 위 목록에
 * 오르므로, 이 문장은 빌더가 아직 모르는 키(서버가 먼저 배포한 새 검사)가 섞였을 때만 쓴다 — 목록에 없는 것을 "위 목록"이라고
 * 가리키지 않기 위해서다. 순수 함수.
 *
 * `keys`는 서버 필드명(`genreId`)이고 라벨 맵은 **인자로 받는다** — 셸마다 필드 집합이 다르고
 * build-common은 build-story/build-character를 import할 수 없다.
 */
export function missingFieldsMessage(
  keys: readonly string[],
  labelByKey: Readonly<Record<string, string | undefined>>,
): string {
  const labels = toLabels(keys, labelByKey, OTHER_MISSING_FIELDS_LABEL);

  return `발행하려면 다음 항목을 입력해주세요: ${labels.join(", ")}`;
}
