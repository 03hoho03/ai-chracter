import { describe, expect, it } from "vitest";

import { formatKstDate } from "./formatKstDate";

describe("formatKstDate", () => {
  it("한국 시각 자정 시행은 그날이다", () => {
    expect(formatKstDate("2026-11-20T00:00:00+09:00")).toBe("2026.11.20");
  });

  // UTC 로는 전날 15시라 브라우저 시간대를 따르면 UTC·미국 브라우저에서 하루 앞 날짜가 된다.
  it("UTC 표기로 와도 한국 날짜로 옮긴다", () => {
    expect(formatKstDate("2026-11-19T15:00:00Z")).toBe("2026.11.20");
    expect(formatKstDate("2026-11-19T14:59:59Z")).toBe("2026.11.19");
  });

  it("월·일을 두 자리로 채운다", () => {
    expect(formatKstDate("2026-01-04T03:00:00Z")).toBe("2026.01.04");
  });
});
