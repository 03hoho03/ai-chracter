import { z } from "zod";

import type { UserProfileResponse } from "@/entities/profile";

/** techspec-global-nav-profile.md §3.1 — 프로필 이미지는 텍스트 입력이 아니라 비동기 업로드 컨트롤이
 * 채우는 필드지만, **제출 payload에 들어가는 값이라 폼 상태에 둔다**(별도 useState면 폼이 단일
 * 소스가 아니게 되고 `reset`이 이미지만 되돌리지 못한다). 업로드 성공 시 `setValue`로 넣는다. */
export const editProfileSchema = z.object({
  nickname: z.string().min(1, { message: "닉네임을 입력해주세요" }),
  bio: z.string().max(500, { message: "소개는 500자 이내로 입력해주세요" }),
  profileImageAssetId: z.string().nullable(),
});

export type EditProfileFormValues = z.infer<typeof editProfileSchema>;

/** 서버 → 폼. 짝인 `./formToServer.ts`가 폼 → 서버를 진다. */
export function editProfileDefaultValues(profile: UserProfileResponse): EditProfileFormValues {
  return {
    nickname: profile.nickname,
    bio: profile.bio ?? "",
    profileImageAssetId: profile.profileImageAssetId,
  };
}
