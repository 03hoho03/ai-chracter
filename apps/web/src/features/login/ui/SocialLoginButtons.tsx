import { Button } from "@ai-character-chat/ui/components/button";

import type { SocialProvider } from "@/entities/session";

import { buildSocialLoginUrl } from "../lib/buildSocialLoginUrl";
import { KakaoLoginButton } from "./KakaoLoginButton";

type SocialLoginButtonsProps = {
  redirectTo?: string;
};

function startSocialLogin(provider: SocialProvider, redirectTo?: string) {
  window.location.href = buildSocialLoginUrl(provider, redirectTo);
}

/** "또는" 구분선 + 소셜 로그인 버튼 묶음. 로그인 화면과 회원가입 화면이 같은 묶음을 쓴다 — 가입 화면에서
 * 시작해도 같은 `/auth/{provider}`로 가고, 신규면 백엔드가 온보딩으로 보낸다.
 *
 * 카카오가 위, 구글이 아래다. 구글은 기존 `outline` 그대로 두어 이 묶음에서 유채색 채움은 카카오 하나뿐이다.
 * 두 버튼은 한 그룹이라 서로의 간격(`gap-3`)을 구분선과의 간격(`gap-5`)보다 좁힌다. */
export function SocialLoginButtons({ redirectTo }: SocialLoginButtonsProps) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <div className="h-px flex-1 bg-border" />
        또는
        <div className="h-px flex-1 bg-border" />
      </div>

      <div className="flex flex-col gap-3">
        <KakaoLoginButton onClick={() => startSocialLogin("kakao", redirectTo)} />
        <Button type="button" variant="outline" size="lg" onClick={() => startSocialLogin("google", redirectTo)}>
          구글로 로그인
        </Button>
      </div>
    </div>
  );
}
