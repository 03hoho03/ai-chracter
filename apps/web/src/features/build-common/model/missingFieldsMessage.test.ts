import { describe, expect, it } from "vitest";

import { missingFieldsMessage } from "./missingFieldsMessage";

/** 서버 필드명 → 라벨 맵의 모양만 옮긴 픽스처 — 검증 대상은 문구 조립이지 맵의 내용이 아니라 필요한 키만 남긴다. */
const MISSING_FIELD_LABELS: Record<string, string> = {
  thumbnailAssetId: "대표 이미지",
  genreId: "장르",
  target: "타겟",
};

describe("missingFieldsMessage", () => {
  it("라벨을 찾은 키를 맵 순서가 아니라 인자 순서대로 나열한다", () => {
    expect(missingFieldsMessage(["target", "genreId"], MISSING_FIELD_LABELS)).toBe(
      "발행하려면 다음 항목을 입력해주세요: 타겟, 장르",
    );
  });

  it("라벨이 없는 키는 영문 원문 대신 일반 문구 하나로 접는다 (빌더가 모르는 키)", () => {
    const message = missingFieldsMessage(["genreId", "situationNotes.newRule"], MISSING_FIELD_LABELS);

    expect(message).toBe("발행하려면 다음 항목을 입력해주세요: 장르, 그 밖의 필수 항목");
    expect(message).not.toContain("newRule");
  });

  it("라벨이 하나도 없어도 문장이 비지 않는다", () => {
    expect(missingFieldsMessage(["situationNotes.newRule"], MISSING_FIELD_LABELS)).toBe(
      "발행하려면 다음 항목을 입력해주세요: 그 밖의 필수 항목",
    );
  });

  it("키가 없어도 항목 자리가 빈 문장을 만들지 않는다", () => {
    expect(missingFieldsMessage([], MISSING_FIELD_LABELS)).toBe(
      "발행하려면 다음 항목을 입력해주세요: 그 밖의 필수 항목",
    );
  });

  it("같은 라벨로 접히는 키가 여럿이어도 한 번만 나열한다", () => {
    expect(missingFieldsMessage(["genreId", "genreId"], MISSING_FIELD_LABELS)).toBe(
      "발행하려면 다음 항목을 입력해주세요: 장르",
    );
  });
});
