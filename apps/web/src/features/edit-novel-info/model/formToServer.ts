import type { components } from "@ai-character-chat/api-types";

import type { SynopsisFormValues, TitleFormValues } from "./novelInfoSchema";

type NovelUpdateRequest = components["schemas"]["NovelUpdateRequest"];

// 서버는 보낸 칸만 고치므로 폼마다 자기 칸 하나만 싣는다. 스키마는 공백을 걷은 값으로 검사만 하고 값은 그대로 두므로,
// 앞뒤 공백은 여기서 걷는다.

/** 제목 폼값 → `PATCH /novels/{id}` 본문. */
export function titleFormToServer(values: TitleFormValues): NovelUpdateRequest {
  return { title: values.title.trim() };
}

/** 소개 폼값 → `PATCH /novels/{id}` 본문. 공백만 남으면 빈 글이 되어 소개를 지운다. */
export function synopsisFormToServer(values: SynopsisFormValues): NovelUpdateRequest {
  return { synopsis: values.synopsis.trim() };
}
