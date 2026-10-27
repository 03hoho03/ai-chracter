import { describe, expect, it } from "vitest";

import type { StoryBuilderFormValues } from "@/features/build-story";

import { storyDraftText } from "./draftText";

function formValues(): StoryBuilderFormValues {
  return {
    profile: { name: "여름밤의 항해", oneLiner: "", image: { assetId: "asset-thumbnail" } },
    storySetting: {
      promptTemplate: "basic",
      worldSetting: "근미래 해양 도시",
      developmentExamples: [{ userLine: "무슨 일이야?", assistantLine: "폭풍우로 배가 좌초된다" }],
      userGoal: "",
      rules: undefined,
      customPrompt: undefined,
      sceneHeaderEnabled: true,
    },
    startingSetups: [
      {
        id: "setup-1",
        name: "표류 첫날",
        prologue: "낯선 해변에서 눈을 뜬다.",
        openingSituation: "",
        playGuide: undefined,
        suggestedReplies: ["주변을 둘러본다"],
        initialScenePlace: "낯선 해변",
        initialSceneTime: "",
        stats: [
          {
            id: "stat-1",
            name: "체력",
            icon: "heart",
            color: "rose",
            min: 0,
            max: 100,
            initial: 80,
            unit: "",
            description: "신체 상태",
            perTurnDelta: null,
            rules: [{ id: "rule-1", condition: "다치면", delta: -10 }],
            hiddenFromPlayer: false,
            playerDescription: "",
            signalHiddenChange: false,
          },
        ],
        endings: [
          {
            id: "ending-1",
            name: "귀환",
            turnGate: 20,
            judgePrompt: "구조선을 만났는가",
            statRules: [{ kind: "rule", id: "er-1", statId: "stat-1", operator: ">=", value: 50, nextOp: null }],
            epilogue: "",
            hint: "",
            priorityStatId: "stat-1",
          },
        ],
        situationNotes: [
          {
            id: "sn-1",
            name: "빈사",
            content: "숨이 가쁘다",
            conditionRules: [{ kind: "rule", id: "cr-1", statId: "stat-1", operator: "<", value: 10, nextOp: null }],
          },
        ],
      },
      {
        id: "setup-2",
        name: "구조 요청",
        prologue: "무전기가 지직거린다.",
        suggestedReplies: [],
        stats: [],
        endings: [],
        situationNotes: [],
      },
    ],
    keywordNotes: [
      {
        id: "note-1",
        content: "밤에는 늑대가 운다.",
        triggerKeywords: ["밤", "늑대"],
        scope: { kind: "startingSetup", startingSetupId: "setup-1" },
        name: "늑대",
        excludeKeywords: [],
        stickyTurns: 2,
        alwaysOn: false,
      },
    ],
    shortcuts: [{ id: "shortcut-1", name: "회상", description: "회상 장면", prompt: "회상을 묘사해줘" }],
    mediaBook: {
      people: [{ id: "00000000-0000-4000-8000-0000000000a1", name: "에리" }],
      scenes: [{ id: "00000000-0000-4000-8000-0000000000b1", name: "기쁨" }],
      cells: [
        {
          id: "00000000-0000-4000-8000-0000000000c1",
          personId: "00000000-0000-4000-8000-0000000000a1",
          sceneId: "00000000-0000-4000-8000-0000000000b1",
          imageAssetId: "00000000-0000-4000-8000-0000000000d1",
          imageUrl: "https://example.com/d1_thumb.webp?X-Amz-Signature=abc",
          imageWidth: 512,
          imageHeight: 683,
          situationDescription: "합격 소식에 웃는다",
          unlockHint: "",
          excludeFromChat: false,
        },
      ],
    },
    registration: {
      description: "표류한 선원들의 생존기",
      genre: "genre-adventure",
      target: "all",
      hashtags: [],
      visibility: "public",
      novelPermission: "forbidden",
    },
  };
}

describe("storyDraftText", () => {
  // 탭 배열은 시작설정·스탯·상황 노트가 미디어 북·키워드북·단축어보다 앞이지만, 기본 설정 묶음이 시작 장면 묶음보다 먼저 선다.
  it("묶음 순서로 절을 세우고, 중첩 목록은 바깥 항목부터 순번을 붙인다", () => {
    expect(storyDraftText(formValues())).toBe(
      [
        "[기본 설정 › 프로필]",
        "이름: 여름밤의 항해",
        "",
        "[기본 설정 › 설정]",
        "스토리 설정/정보: 근미래 해양 도시",
        "1번째 전개 예시 사용자 메시지: 무슨 일이야?",
        "1번째 전개 예시 스토리 응답: 폭풍우로 배가 좌초된다",
        "",
        "[기본 설정 › 미디어 북]",
        "1번째 칸 상황 설명: 합격 소식에 웃는다",
        "",
        "[기본 설정 › 키워드북]",
        "1번째 노트 정보: 밤에는 늑대가 운다.",
        "1번째 노트 트리거 키워드: 밤, 늑대",
        "1번째 노트 이름: 늑대",
        "",
        "[기본 설정 › 단축어]",
        "1번째 단축어 이름: 회상",
        "1번째 단축어 설명: 회상 장면",
        "1번째 단축어 실행될 프롬프트: 회상을 묘사해줘",
        "",
        "[시작 장면 › 시작설정]",
        "1번째 시작설정 이름: 표류 첫날",
        "1번째 시작설정 프롤로그: 낯선 해변에서 눈을 뜬다.",
        "1번째 시작설정 추천 답변: 주변을 둘러본다",
        "1번째 시작설정 첫 장면 장소: 낯선 해변",
        "2번째 시작설정 이름: 구조 요청",
        "2번째 시작설정 프롤로그: 무전기가 지직거린다.",
        "",
        "[시작 장면 › 스탯]",
        "1번째 시작설정 1번째 스탯 이름: 체력",
        "1번째 시작설정 1번째 스탯 설명: 신체 상태",
        "1번째 시작설정 1번째 스탯 1번째 규칙 조건: 다치면",
        "",
        "[시작 장면 › 상황 노트]",
        "1번째 시작설정 1번째 상황 노트 이름: 빈사",
        "1번째 시작설정 1번째 상황 노트 상황: 숨이 가쁘다",
        "",
        "[시작 장면 › 엔딩]",
        "1번째 시작설정 1번째 엔딩 이름: 귀환",
        "1번째 시작설정 1번째 엔딩 판단 프롬프트: 구조선을 만났는가",
        "",
        "[공개 준비 › 등록]",
        "등록 설명: 표류한 선원들의 생존기",
        "",
        "(그림 2장은 복사에서 빠져요)",
      ].join("\n"),
    );
  });

  // 서명된 그림 주소는 남에게 보이면 안 되고, id·고르는 칸의 원시값(아이콘·색·연산자·스탯 id·장르 id·공개범위)은 글로 읽으면 뜻이 없다.
  it("그림 주소·id·고르는 칸 값을 싣지 않는다", () => {
    const text = storyDraftText(formValues());
    for (const raw of ["http", "X-Amz", "setup-1", "stat-1", "heart", "rose", ">=", "genre-adventure", "public", "forbidden", "basic", "0000"]) {
      expect(text).not.toContain(raw);
    }
  });
});
