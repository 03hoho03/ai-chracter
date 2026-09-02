import { describe, expect, it } from "vitest";

import { handleSiteVerification } from "./siteVerification";

const NAVER_PATH = "/naver51990167ef24f88190ab863b33dae806.html";

describe("handleSiteVerification", () => {
  it("등록된 소유확인 경로에 검증기가 기대하는 본문을 준다", async () => {
    const response = handleSiteVerification(NAVER_PATH);

    expect(response?.status).toBe(200);
    // 네이버는 본문이 `naver-site-verification: <파일명>`이기를 요구한다.
    expect(await response?.text()).toBe(
      "naver-site-verification: naver51990167ef24f88190ab863b33dae806.html",
    );
  });

  it("그 밖의 경로는 건드리지 않는다", () => {
    expect(handleSiteVerification("/")).toBeUndefined();
    expect(handleSiteVerification("/naver-wrong.html")).toBeUndefined();
    // 확장자를 뗀 형태로 오면 우리 것이 아니다 — Pages 308을 우리가 대신 처리하지 않는다.
    expect(handleSiteVerification("/naver51990167ef24f88190ab863b33dae806")).toBeUndefined();
  });
});
