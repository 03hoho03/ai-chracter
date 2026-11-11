import type { NovelCharacterUpdateRequest } from "@/entities/novel";

import type { CharacterMemoFormValues, CharacterNameFormValues } from "./characterForm";

// 서버는 보낸 칸만 고치므로 폼마다 자기 칸 하나만 싣는다. 스키마는 공백을 걷은 값으로 검사만 하고 값은 그대로 두므로,
// 앞뒤 공백은 여기서 걷는다. 칸은 늘 문자열로 싣는다 — 메모 폼은 저장한 값으로 다시 굳힐 때 이 값을 쓴다.

/** 인물 이름 폼값 → `PATCH /novels/{id}/characters/{characterId}` 본문. */
export function nameFormToServer(values: CharacterNameFormValues): { name: NonNullable<NovelCharacterUpdateRequest["name"]> } {
  return { name: values.name.trim() };
}

/** 인물 메모 폼값 → 같은 엔드포인트 본문. 공백만 남으면 빈 글이 되어 메모를 지운다. */
export function memoFormToServer(values: CharacterMemoFormValues): { memo: NonNullable<NovelCharacterUpdateRequest["memo"]> } {
  return { memo: values.memo.trim() };
}
