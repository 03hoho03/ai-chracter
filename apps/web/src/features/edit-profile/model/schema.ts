import { z } from "zod";

import type { UserProfileResponse } from "@/entities/profile";

/** techspec-global-nav-profile.md §3.1 — 필드 3개뿐인 단순 폼이라 formToServer/serverToForm 분리 없이
 * 구현한다(마이페이지 비밀번호 변경과 동일한 판단). 프로필 이미지는 텍스트 필드가 아니라 별도 업로드
 * 컨트롤(비동기 assetId)이라 이 zod 스키마에는 포함하지 않는다. */
export const editProfileSchema = z.object({
  nickname: z.string().min(1, { message: "닉네임을 입력해주세요" }),
  bio: z.string().max(500, { message: "소개는 500자 이내로 입력해주세요" }),
});

export type EditProfileFormValues = z.infer<typeof editProfileSchema>;

export function editProfileDefaultValues(profile: UserProfileResponse): EditProfileFormValues {
  return { nickname: profile.nickname, bio: profile.bio ?? "" };
}
