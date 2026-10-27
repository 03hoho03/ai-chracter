import { describe, expect, it } from "vitest";

import type { CharacterBuilderFormValues } from "@/features/build-character";

import { characterDraftText } from "./draftText";

function formValues(): CharacterBuilderFormValues {
  return {
    profile: { name: "루나", oneLiner: "달빛 마법사", image: { assetId: "asset-thumbnail" } },
    intro: {
      firstMessage: "안녕, 나는 루나야.",
      exampleDialogues: [{ id: "dlg-1", userLine: "안녕?", characterLine: "반가워!" }],
      playGuide: "",
    },
    prompt: { characterPrompt: "너는 상냥한 달빛 마법사다." },
    situationalImages: [
      { id: "img-1", image: { assetId: "asset-1" }, situationDescription: "웃을 때" },
      { id: "img-2", image: null, situationDescription: "화날 때" },
    ],
    registration: {
      description: "달빛 마법사 루나 이야기",
      genre: "genre-fantasy",
      target: "all",
      hashtags: ["판타지", "마법"],
      visibility: "public",
      novelPermission: "forbidden",
    },
  };
}

describe("characterDraftText", () => {
  // 탭 배열은 인트로가 둘째지만 묶음 순서로는 기본 설정(프로필·프롬프트·상황별 이미지) 다음이다.
  it("묶음 순서로 탭마다 칸 이름을 붙여 옮긴다", () => {
    expect(characterDraftText(formValues())).toBe(
      [
        "[기본 설정 › 프로필]",
        "이름: 루나",
        "한줄소개: 달빛 마법사",
        "",
        "[기본 설정 › 프롬프트]",
        "캐릭터 프롬프트: 너는 상냥한 달빛 마법사다.",
        "",
        "[기본 설정 › 상황별 이미지]",
        "1번째 상황별 이미지 노출할 상황: 웃을 때",
        "2번째 상황별 이미지 노출할 상황: 화날 때",
        "",
        "[시작 장면 › 인트로]",
        "인트로 (첫 대화 본문): 안녕, 나는 루나야.",
        "1번째 예시 대화 사용자 대사: 안녕?",
        "1번째 예시 대화 캐릭터 대사: 반가워!",
        "",
        "[공개 준비 › 등록]",
        "등록 설명: 달빛 마법사 루나 이야기",
        "해시태그: 판타지, 마법",
        "",
        "(그림 2장은 복사에서 빠져요)",
      ].join("\n"),
    );
  });

  it("고르는 칸의 원시값과 id 를 싣지 않는다", () => {
    const text = characterDraftText(formValues());
    for (const raw of ["genre-fantasy", "all", "public", "forbidden", "asset-", "dlg-1", "img-1"]) {
      expect(text).not.toContain(raw);
    }
  });
});
