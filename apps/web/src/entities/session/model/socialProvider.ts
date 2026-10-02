import type { MeResponse } from "../api/sessionQueryOptions";

/** 소셜 로그인 제공자. 손으로 적지 않고 `/me` 응답 타입에서 도출한다 — 백엔드가 제공자를 더하면
 * 아래 라벨 `Record`가 키 누락으로 컴파일 단계에서 깨져, 화면마다 이름을 빠뜨리는 일을 막는다. */
export type SocialProvider = NonNullable<MeResponse["socialProvider"]>;

/** 사용자에게 보이는 제공자 이름. 로그인 안내 문구와 마이페이지가 같은 이름을 쓰도록 한 곳에 둔다. */
export const SOCIAL_PROVIDER_LABELS: Record<SocialProvider, string> = {
  google: "구글",
  kakao: "카카오",
};
