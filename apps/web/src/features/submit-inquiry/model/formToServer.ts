import type { components } from "@ai-character-chat/api-types";

import type { SubmitInquiryFormValues } from "./schema";

type InquiryCreateRequest = components["schemas"]["InquiryCreateRequest"];

/** 폼값 → 서버 계약(techspec.md §5-4). 지금은 필드 이름·모양이 그대로 겹쳐 본문이 매핑 한 줄뿐이지만,
 * 변환 경계를 한 곳에 두는 것이 이 저장소의 폼 규약이다(`apps/web/CLAUDE.md` — "formToServer/serverToForm이
 * 이름·모양 변환을 전담한다", `build-character`·`build-story` 동형). 구조적 호환에만 기대면 서버가 필드를
 * 하나 고치는 순간 폼 스키마까지 함께 끌려가고, 그때 어디를 고쳐야 하는지가 화면 코드에 흩어진다. */
export function formToServer(values: SubmitInquiryFormValues): InquiryCreateRequest {
  return {
    category: values.category,
    title: values.title,
    body: values.body,
    attachmentAssetId: values.attachmentAssetId,
  };
}
