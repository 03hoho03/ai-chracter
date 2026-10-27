import { describe, expect, it } from "vitest";

import { draftPlainText } from "./draftPlainText";

// 실제 빌더를 닮은 작은 표 — 배열 순서와 묶음 순서가 다르고(`notes` 탭이 배열 앞이지만 뒤 묶음), 중첩 배열과 글 목록, 고르는 칸,
// 그림 칸, 화면에 칸이 없는 값(id·표시용 주소)을 품는다.
const TABS = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "notes", label: "노트", fields: ["setups.*.notes"], preview: "chat" },
  { id: "setup", label: "시작설정", fields: ["setups"], preview: "chat" },
  { id: "register", label: "등록", fields: ["registration"], preview: "card" },
] as const;

const STEPS = { profile: "basics", setup: "basics", notes: "opening", register: "publish" } as const;

const LABELS = {
  "profile.image": { label: "대표 이미지" },
  "profile.name": { label: "이름" },
  "profile.oneLiner": { label: "한줄소개" },
  setups: { label: "시작설정" },
  "setups.*.name": { label: "이름" },
  "setups.*.replies": { label: "추천 답변" },
  "setups.*.notes": { label: "노트" },
  "setups.*.notes.*.content": { label: "내용" },
  "registration.genre": { label: "장르" },
  "registration.description": { label: "등록 설명" },
};

const CHOICES = new Set(["registration.genre"]);

const OPTIONS = { tabs: TABS, steps: STEPS, labels: LABELS, choiceFields: CHOICES };

const VALUES = {
  profile: { image: { assetId: "asset-1" }, name: "하늘", oneLiner: "" },
  setups: [
    {
      id: "setup-a",
      name: "첫 만남",
      replies: ["안녕", "  ", "누구세요"],
      notes: [
        { id: "note-1", content: "비 오는 밤", imageUrl: "https://example.test/presigned?sig=1", imageAssetId: "asset-2" },
        { id: "note-2", content: "   " },
      ],
    },
    { id: "setup-b", name: "재회", replies: [], notes: [{ id: "note-3", content: "여름 바다" }] },
  ],
  registration: { genre: "genre-uuid-1234", description: "둘째 줄도\n있다" },
};

describe("draftPlainText", () => {
  it("묶음 순서로 절을 세우고 칸 이름을 붙인다", () => {
    expect(draftPlainText(VALUES, OPTIONS)).toBe(
      [
        "[기본 설정 › 프로필]",
        "이름: 하늘",
        "",
        "[기본 설정 › 시작설정]",
        "1번째 시작설정 이름: 첫 만남",
        "1번째 시작설정 추천 답변: 안녕, 누구세요",
        "2번째 시작설정 이름: 재회",
        "",
        "[시작 장면 › 노트]",
        "1번째 시작설정 1번째 노트 내용: 비 오는 밤",
        "2번째 시작설정 1번째 노트 내용: 여름 바다",
        "",
        "[공개 준비 › 등록]",
        "등록 설명: 둘째 줄도\n있다",
        "",
        "(그림 2장은 복사에서 빠져요)",
      ].join("\n"),
    );
  });

  // 복사한 글은 작가가 다른 곳에 붙여 두는 것이다 — 서명된 그림 주소·내부 id·고르는 칸의 원시값은 뜻이 없거나 남에게 보이면 안 된다.
  it("그림 주소·id·고르는 칸 값을 싣지 않는다", () => {
    const text = draftPlainText(VALUES, OPTIONS);
    expect(text).not.toContain("http");
    expect(text).not.toContain("asset-");
    expect(text).not.toContain("setup-a");
    expect(text).not.toContain("note-1");
    expect(text).not.toContain("genre-uuid");
  });

  it("빈 칸은 싣지 않고, 글이 하나도 없는 탭은 절도 없다", () => {
    const text = draftPlainText(
      { profile: { image: null, name: "  ", oneLiner: "" }, setups: [], registration: { genre: null, description: "설명" } },
      OPTIONS,
    );
    expect(text).toBe(["[공개 준비 › 등록]", "등록 설명: 설명"].join("\n"));
  });

  it("글도 그림도 없으면 빈 글이다", () => {
    expect(
      draftPlainText({ profile: { image: null, name: "", oneLiner: "" }, setups: [], registration: { genre: null, description: "" } }, OPTIONS),
    ).toBe("");
  });
});
