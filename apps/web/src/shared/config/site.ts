/**
 * 화면에 보이는 서비스 이름·한 줄 소개·문의 주소의 단일 소스. Worker(`worker/meta.ts`)는 따로 `SITE_NAME`을
 * 둔다 — 별도 런타임이라 `src/`를 import하지 못한다. `index.html`의 meta description도 같은 이유로 사본이
 * 아니라 별도 문장이다(검색 결과용이라 길이·어조가 다르다) — 정체를 다르게 말하지 않는지만 맞춘다.
 */
export const SITE_NAME = "또나";

/** 이 서비스가 무엇인지 말하는 한 문장. 홈(비로그인 첫 줄)과 `/about` 첫 문장이 이 상수 하나를 쓴다 —
 * 둘이 다르게 쓰이기 시작하면 정체 문장이 둘이 된다. `worker/aboutMeta.ts`의 `/about` description이 같은 문장의
 * 사본이라(별도 런타임) 이 문장을 고치면 그쪽과 그 테스트도 함께 고친다. */
export const SITE_INTRO = `${SITE_NAME}는 AI 캐릭터와 대화하고, 직접 만든 캐릭터와 스토리를 다른 사람과 나누는 서비스예요.`;

export const CONTACT_EMAIL = "contact@ddona.site";
