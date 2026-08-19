import { describe, expect, it } from "vitest";

import { isCrawler } from "./crawler";

/** 실제로 관측되는 UA 문자열을 쓴다 — 목록 토큰만 재나열하면 검사가 자기 자신을 확인할 뿐이다. */
const CRAWLER_USER_AGENTS = {
  googlebot:
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
  /** 서치콘솔 `게재된 URL 테스트`·리치 결과 테스트. UA에 googlebot이 없어 따로 잡아야 한다. */
  googleInspectionTool:
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36 (compatible; Google-InspectionTool/1.0;)",
  yeti: "Mozilla/5.0 (compatible; Yeti/1.1; +http://naver.me/spd)",
  kakaotalk:
    "Mozilla/5.0 (compatible; kakaotalk-scrap/1.0; +https://devtalk.kakao.com/tags/scrap)",
  facebook:
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
  twitter: "Twitterbot/1.0",
  slack: "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
};

const HUMAN_USER_AGENTS = {
  chrome:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  iosSafari:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
  androidChrome:
    "Mozilla/5.0 (Linux; Android 15; SM-S926N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
};

describe("isCrawler", () => {
  it.each(Object.entries(CRAWLER_USER_AGENTS))(
    "크롤러 UA를 판별한다: %s",
    (_name, userAgent) => {
      expect(isCrawler(userAgent)).toBe(true);
    },
  );

  it.each(Object.entries(HUMAN_USER_AGENTS))(
    "일반 브라우저 UA는 크롤러가 아니다: %s",
    (_name, userAgent) => {
      expect(isCrawler(userAgent)).toBe(false);
    },
  );

  it("대소문자를 가리지 않는다", () => {
    expect(isCrawler("KakaoTalk-Scrap/1.0")).toBe(true);
  });

  it("UA 헤더가 없으면 크롤러가 아니다", () => {
    expect(isCrawler(null)).toBe(false);
    expect(isCrawler(undefined)).toBe(false);
    expect(isCrawler("")).toBe(false);
  });
});
