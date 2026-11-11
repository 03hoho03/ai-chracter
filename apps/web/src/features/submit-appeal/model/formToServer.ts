import type { components } from "@ai-character-chat/api-types";

import type { AppealTarget } from "../api/useSubmitAppealMutation";
import type { SubmitAppealFormValues } from "./submitAppealSchema";

type AppealCreateRequest = components["schemas"]["AppealCreateRequest"];

/** 폼값 + 이의제기 대상 → `POST /appeals` 본문. 대상은 종류마다 id 칸 이름이 달라 서버의 `targetId` 하나로 모은다.
 * 사유는 스키마가 이미 앞뒤 공백을 걷었다. */
export function formToServer(values: SubmitAppealFormValues, target: AppealTarget): AppealCreateRequest {
  return {
    targetKind: target.kind,
    targetId: target.kind === "publish-rejection" ? target.rejectionId : target.actionId,
    reasonText: values.reasonText,
  };
}
