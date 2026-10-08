import { describe, expect, it } from "vitest";

import { describeMailOrderReport } from "./businessInfo";

describe("describeMailOrderReport", () => {
  it("신고번호가 없으면 면제로 표기하고 확인 링크를 두지 않는다", () => {
    expect(describeMailOrderReport(null, "865-12-03163")).toEqual({
      label: "신고 면제(간이과세자)",
      verifyUrl: null,
    });
  });

  it("신고번호가 있으면 그 번호를 표기하고 하이픈을 뺀 사업자등록번호로 공정위 확인 링크를 만든다", () => {
    expect(describeMailOrderReport("제2026-경북구미-0001호", "865-12-03163")).toEqual({
      label: "제2026-경북구미-0001호",
      verifyUrl: "https://www.ftc.go.kr/bizCommPop.do?wrkr_no=8651203163",
    });
  });
});
