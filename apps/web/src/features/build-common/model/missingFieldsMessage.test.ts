import { describe, expect, it } from "vitest";

import { fieldLabelByFormPath, invalidFieldsMessage, missingFieldsMessage } from "./missingFieldsMessage";

/** `StoryBuilderShell`의 두 맵을 값만 옮긴 픽스처(widgets를 import하면 레이어를 거스른다) — 검증
 * 대상은 문구 조립이지 맵의 내용이 아니라 필요한 키만 남긴다. */
const MISSING_FIELD_LABELS: Record<string, string> = {
  thumbnailAssetId: "대표 이미지",
  genreId: "장르",
  target: "타겟",
};

const MISSING_FIELD_FORM_PATH: Record<string, string> = {
  thumbnailAssetId: "profile.image",
  genreId: "registration.genre",
  target: "registration.target",
};

describe("missingFieldsMessage", () => {
  it("라벨을 찾은 키를 맵 순서가 아니라 인자 순서대로 나열한다", () => {
    expect(missingFieldsMessage(["target", "genreId"], MISSING_FIELD_LABELS)).toBe(
      "발행하려면 다음 항목을 입력해주세요: 타겟, 장르",
    );
  });

  it("라벨이 없는 키는 영문 원문 대신 일반 문구 하나로 접는다 (BP-4, F-8의 인덱스 경로)", () => {
    const message = missingFieldsMessage(["genreId", "startingSetups[0].prologue"], MISSING_FIELD_LABELS);

    expect(message).toBe("발행하려면 다음 항목을 입력해주세요: 장르, 그 밖의 필수 항목");
    expect(message).not.toContain("startingSetups");
  });

  it("라벨이 하나도 없어도 문장이 비지 않는다", () => {
    expect(missingFieldsMessage(["startingSetups[0].prologue"], MISSING_FIELD_LABELS)).toBe(
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

describe("invalidFieldsMessage", () => {
  const LABEL_BY_FORM_PATH = fieldLabelByFormPath(MISSING_FIELD_FORM_PATH, MISSING_FIELD_LABELS);

  it("클라 검증 경로는 '입력'이 아니라 '확인'을 시킨다", () => {
    expect(invalidFieldsMessage(["registration.genre", "registration.target"], LABEL_BY_FORM_PATH)).toBe(
      "발행하려면 다음 항목을 확인해주세요: 장르, 타겟",
    );
  });

  it("라벨 없는 키를 '필수 항목'이라고 부르지 않는다 (시작설정 .max(4) 위반은 삭제가 답이다)", () => {
    const message = invalidFieldsMessage(["startingSetups.root"], LABEL_BY_FORM_PATH);

    expect(message).toBe("발행하려면 다음 항목을 확인해주세요: 그 밖의 항목");
    expect(message).not.toContain("입력해주세요");
    expect(message).not.toContain("필수");
    expect(message).not.toContain("startingSetups");
  });

  it("서버 400 경로와 같은 라벨 목록을 쓰고 문장만 갈린다 (BP-3)", () => {
    const fromServer = missingFieldsMessage(["genreId", "target"], MISSING_FIELD_LABELS);
    const fromClient = invalidFieldsMessage(["registration.genre", "registration.target"], LABEL_BY_FORM_PATH);

    expect(fromServer).toBe("발행하려면 다음 항목을 입력해주세요: 장르, 타겟");
    expect(fromClient).toBe("발행하려면 다음 항목을 확인해주세요: 장르, 타겟");
  });
});

describe("fieldLabelByFormPath", () => {
  it("서버 필드명을 키로 하는 두 맵에서 폼 경로 → 라벨을 파생시킨다", () => {
    expect(fieldLabelByFormPath(MISSING_FIELD_FORM_PATH, MISSING_FIELD_LABELS)).toEqual({
      "profile.image": "대표 이미지",
      "registration.genre": "장르",
      "registration.target": "타겟",
    });
  });

  it("한쪽 맵에만 있는 필드는 빠진다 (폼 경로가 없거나 라벨이 없는 필드)", () => {
    const result = fieldLabelByFormPath(
      { ...MISSING_FIELD_FORM_PATH, settingText: "storySetting.worldSetting" },
      { ...MISSING_FIELD_LABELS, characterPrompt: "캐릭터 프롬프트" },
    );

    expect(result["storySetting.worldSetting"]).toBeUndefined();
    expect(Object.values(result)).not.toContain("캐릭터 프롬프트");
  });
});
