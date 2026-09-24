/** 인증 폼(구글 온보딩·비밀번호 변경) 오류 배너. (엔드포인트, status) → 배너 매핑은 각 feature의
 * `model`이 갖고, 두 feature가 같이 읽는 모양·표식만 여기 둔다(features끼리는 import하지 못한다 — FSD). */
export type AuthFormErrorBanner = {
  message: string;
  /** 배너 안에 `/login` 링크를 둘지 — 이 폼을 다시 제출해서는 빠져나갈 수 없는 실패다. */
  shouldShowLoginLink: boolean;
};

/** RHF root 에러의 `type` — 컴포넌트는 이 표식으로 배너 안에 로그인 링크를 그릴지 안다
 * (선례: `EmailVerifyStep`의 `type: "server"`). */
export const LOGIN_LINK_ERROR_TYPE = "login-link";
