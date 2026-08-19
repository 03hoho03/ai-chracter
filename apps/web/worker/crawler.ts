/**
 * 메타를 주입할 대상 크롤러의 User-Agent 조각. 전부 소문자로 적고 `includes`로만 비교한다 —
 * 정규식은 UA마다 형식이 제각각이라 얻을 게 없고 잘못 쓰면 백트래킹 비용만 남는다.
 *
 * 앞쪽은 검색엔진(구글·빙·네이버 Yeti·다음·덕덕고·애플·얀덱스),
 * 뒤쪽은 링크 미리보기를 긁는 SNS·메신저 크롤러다.
 *
 * `google-inspectiontool`은 색인용 크롤러가 아니라 **서치콘솔의 `게재된 URL 테스트`와
 * 리치 결과 테스트**가 쓰는 별도 UA다. UA에 `googlebot`이 들어 있지 않아 이게 없으면
 * 실제 색인은 정상인데 확인 도구에서만 주입 전 HTML이 보인다(2026-08-20 프로덕션에서 관측).
 */
const CRAWLER_USER_AGENT_TOKENS = [
  "googlebot",
  "google-inspectiontool",
  "bingbot",
  "yeti",
  "daum",
  "duckduckbot",
  "applebot",
  "yandex",
  "facebookexternalhit",
  "twitterbot",
  "slackbot",
  "telegrambot",
  "discordbot",
  "whatsapp",
  "linkedinbot",
  "line-poker",
  "kakaotalk-scrap",
  "kakaostory-linkinfo",
];

/**
 * 크롤러 UA인지 판별한다. 메타 주입은 이 함수가 true일 때만 한다 —
 * 주입 내용이 React가 클라이언트에서 만드는 것과 동일하므로 클로킹이 아니고,
 * 일반 사용자는 지금과 똑같은 응답(추가 API 왕복 0회)을 받아야 한다.
 */
export function isCrawler(userAgent: string | null | undefined): boolean {
  if (!userAgent) return false;

  const normalized = userAgent.toLowerCase();
  return CRAWLER_USER_AGENT_TOKENS.some((token) => normalized.includes(token));
}
