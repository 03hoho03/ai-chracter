import type { UserProfileResponse } from "@/entities/profile";

import type { EditProfileFormValues } from "./schema";

/** 서버 → 폼. 짝인 `./formToServer.ts`가 폼 → 서버를 진다. */
export function serverToForm(profile: UserProfileResponse): EditProfileFormValues {
  return {
    nickname: profile.nickname,
    bio: profile.bio ?? "",
    profileImageAssetId: profile.profileImageAssetId,
  };
}
