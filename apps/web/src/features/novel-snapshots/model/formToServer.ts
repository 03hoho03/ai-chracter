import type { components } from "@ai-character-chat/api-types";

import type { SnapshotNameFormValues } from "./snapshotName";

type NovelSnapshotCreateRequest = components["schemas"]["NovelSnapshotCreateRequest"];

/** 버전 이름 폼값 → `POST /novels/{id}/snapshots` 본문. 스키마는 공백을 걷은 값으로 검사만 하고 값은 그대로 두므로
 * 앞뒤 공백은 여기서 걷는다. */
export function formToServer(values: SnapshotNameFormValues): NovelSnapshotCreateRequest {
  return { name: values.name.trim() };
}
