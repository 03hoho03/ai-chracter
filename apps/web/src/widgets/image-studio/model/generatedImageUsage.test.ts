import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toGeneratedImageDeleteConflictMessage, toGeneratedImageUsageView } from "./generatedImageUsage";

const WORK = { contentId: "c1", contentType: "character", contentTitle: "작품", field: "thumbnail" } as const;
const MY_NOVEL = { novelId: "n1", novelTitle: "내 소설", field: "illustration" } as const;
const OTHER_NOVEL = { novelId: null, novelTitle: null, field: "illustration" } as const;

describe("toGeneratedImageUsageView", () => {
  it("소설 사용처가 없으면(삽화 스위치를 켠 적 없는 응답) 지금 화면과 같다", () => {
    const unused = toGeneratedImageUsageView({ usages: [], novelUsages: [] });
    expect(unused).toEqual({
      isInUse: false,
      usageCount: 0,
      heading: "사용 중인 작품",
      deleteBlockedReason: "위 작품에서 사용 중이라 삭제할 수 없어요.",
      novelRows: [],
    });
    const usedByWork = toGeneratedImageUsageView({ usages: [WORK], novelUsages: [] });
    expect(usedByWork).toMatchObject({ isInUse: true, usageCount: 1, heading: "사용 중인 작품", novelRows: [] });
  });

  it("소설 칸이 없는 응답도 지금 화면과 같다", () => {
    expect(toGeneratedImageUsageView({ usages: [WORK] })).toMatchObject({ isInUse: true, usageCount: 1, novelRows: [] });
  });

  it("소설에서만 쓰여도 사용 중이라 삭제를 막는다", () => {
    expect(toGeneratedImageUsageView({ usages: [], novelUsages: [MY_NOVEL] })).toMatchObject({
      isInUse: true,
      usageCount: 1,
      heading: "사용 중인 곳",
      deleteBlockedReason: "위에서 사용 중이라 삭제할 수 없어요.",
    });
  });

  it("배지 수는 작품과 소설 사용처를 더한다", () => {
    expect(toGeneratedImageUsageView({ usages: [WORK], novelUsages: [MY_NOVEL, OTHER_NOVEL] }).usageCount).toBe(3);
  });

  it("내 소설은 제목과 칸, 남의 소설은 제목 없이 원작 이미지로 쓰인다고 말한다", () => {
    expect(
      toGeneratedImageUsageView({
        usages: [],
        novelUsages: [MY_NOVEL, { novelId: "n1", novelTitle: "내 소설", field: "cover" }, OTHER_NOVEL],
      }).novelRows,
    ).toEqual([
      { key: "n1-illustration", title: "내 소설", detail: "삽화" },
      { key: "n1-cover", title: "내 소설", detail: "표지" },
      { key: "other-illustration", title: "다른 작가의 소설", detail: "원작 이미지로 쓰는 중" },
    ]);
  });
});

describe("toGeneratedImageDeleteConflictMessage", () => {
  function conflict(detail: Record<string, unknown>) {
    return new ApiErrorObject({ status: 409, message: "x", detail });
  }

  it("작품에만 쓰였으면 지금 문장 그대로다", () => {
    expect(toGeneratedImageDeleteConflictMessage(conflict({ usages: [WORK], novelUsages: [] }))).toBe(
      "이미지가 방금 작품에 사용되어 삭제할 수 없어요.",
    );
    expect(toGeneratedImageDeleteConflictMessage(conflict({ usages: [WORK] }))).toBe(
      "이미지가 방금 작품에 사용되어 삭제할 수 없어요.",
    );
  });

  it("소설에서 쓰이면 소설도 말한다", () => {
    expect(toGeneratedImageDeleteConflictMessage(conflict({ usages: [], novelUsages: [OTHER_NOVEL] }))).toBe(
      "이미지가 방금 작품이나 소설에 사용되어 삭제할 수 없어요.",
    );
  });
});
