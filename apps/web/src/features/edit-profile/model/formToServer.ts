import type { components } from "@ai-character-chat/api-types";

import type { EditProfileFormValues } from "./schema";

type UpdateProfileRequest = components["schemas"]["UpdateProfileRequest"];

/** 폼값 → 서버 계약. 변환은 여기 하나뿐이다(`apps/web/CLAUDE.md` 폼 규약) — 컴포넌트 안에서
 * 즉석 조립하면 `bio` 정규화 같은 경계 규칙이 화면 코드에 묻힌다.
 *
 * **빈 소개는 `""`가 아니라 `null`이다.** 서버 `bio`는 `str | None`이고 "소개 없음"을 `null`로
 * 표현한다 — 빈 문자열을 보내면 "빈 소개"가 저장돼 프로필에 빈 줄이 남는다. */
export function formToServer(values: EditProfileFormValues): UpdateProfileRequest {
  return {
    nickname: values.nickname,
    bio: values.bio.trim() === "" ? null : values.bio,
    profileImageAssetId: values.profileImageAssetId,
  };
}
