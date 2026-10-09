import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import type { StoryBuilderFormValues } from "./schema";

function requireFirst<T>(items: readonly T[]): T {
  const [first] = items;
  if (!first) throw new Error("fixture empty");
  return first;
}

const PERSON_ID = "00000000-0000-4000-8000-0000000000a1";

function baseFormValues(): StoryBuilderFormValues {
  return {
    profile: { name: "여름밤의 항해", oneLiner: "바다 위 표류기", image: { assetId: "asset-thumbnail" } },
    storySetting: {
      promptTemplate: "basic",
      worldSetting: "근미래 해양 도시",
      developmentExamples: [{ userLine: "무슨 일이 있었는지 설명해주세요", assistantLine: "폭풍우로 배가 좌초된다" }],
      userGoal: "표류에서 살아남아 무사히 귀환한다",
      defaultUserName: "",
      rules: "선원들 앞에서 약한 모습을 보이지 않는다",
      customPrompt: undefined,
    },
    startingSetups: [
      {
        id: "setup-1",
        name: "표류 첫날",
        prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
        openingSituation: "파도 소리만 들린다.",
        playGuide: "생존에 집중하는 톤을 유지하세요.",
        suggestedReplies: ["주변을 둘러본다"],
        stats: [
          {
            id: "stat-1",
            name: "체력",
            icon: "heart",
            color: "rose",
            min: 0,
            max: 100,
            initial: 80,
            unit: "pt",
            description: "생존에 필요한 신체 상태",
            perTurnDelta: -1,
            rules: [],
          },
        ],
        endings: [],
        situationNotes: [],
      },
    ],
    keywordNotes: [
      {
        id: "note-1",
        content: "밤에는 늑대 울음소리가 들린다.",
        triggerKeywords: ["밤", "늑대"],
        scope: { kind: "startingSetup", startingSetupId: "setup-1" },
        name: "늑대 울음",
        excludeKeywords: ["낮"],
        stickyTurns: 2,
        alwaysOn: true,
      },
    ],
    shortcuts: [
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ],
    mediaBook: {
      people: [{ id: "00000000-0000-4000-8000-0000000000a1", name: "에리" }],
      scenes: [{ id: "00000000-0000-4000-8000-0000000000b1", name: "기쁨" }],
      cells: [
        {
          id: "00000000-0000-4000-8000-0000000000c1",
          personId: "00000000-0000-4000-8000-0000000000a1",
          sceneId: "00000000-0000-4000-8000-0000000000b1",
          imageAssetId: "00000000-0000-4000-8000-0000000000d1",
          imageUrl: "https://example.com/00000000-0000-4000-8000-0000000000d1_thumb.webp",
          imageWidth: 512,
          imageHeight: 683,
          situationDescription: "합격 소식을 듣고 웃는다",
          unlockHint: "합격 발표 날",
          excludeFromChat: true,
        },
      ],
    },
    registration: {
      description: "표류한 선원들의 생존기",
      genre: "genre-adventure",
      target: "all",
      hashtags: ["모험"],
      visibility: "public",
    },
  };
}

describe("formToServer", () => {
  it("maps profile/storySetting/startingSetups/registration into the StoryDraftPayload shape", () => {
    expect(formToServer(baseFormValues())).toEqual({
      name: "여름밤의 항해",
      oneLiner: "바다 위 표류기",
      thumbnailAssetId: "asset-thumbnail",
      promptTemplate: "basic",
      settingText: "근미래 해양 도시",
      developmentExamples: [{ userLine: "무슨 일이 있었는지 설명해주세요", assistantLine: "폭풍우로 배가 좌초된다" }],
      userGoal: "표류에서 살아남아 무사히 귀환한다",
      defaultUserName: "",
      rules: "선원들 앞에서 약한 모습을 보이지 않는다",
      customPrompt: null,
      startingSetups: [
        {
          id: "setup-1",
          name: "표류 첫날",
          prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
          openingMessage: "파도 소리만 들린다.",
          playguide: "생존에 집중하는 톤을 유지하세요.",
          suggestedReplies: ["주변을 둘러본다"],
          statDefs: [
            {
              id: "stat-1",
              name: "체력",
              icon: "heart",
              color: "rose",
              minValue: 0,
              maxValue: 100,
              initialValue: 80,
              unit: "pt",
              description: "생존에 필요한 신체 상태",
              perTurnDelta: -1,
              rules: [],
            },
          ],
          endings: [],
          situationNotes: [],
        },
      ],
      keywordNotes: [
        {
          id: "note-1",
          infoText: "밤에는 늑대 울음소리가 들린다.",
          triggerKeywords: ["밤", "늑대"],
          startingSetupId: "setup-1",
          name: "늑대 울음",
          excludeKeywords: ["낮"],
          stickyTurns: 2,
          alwaysOn: true,
        },
      ],
      shortcuts: [
        { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
      ],
      mediaBook: {
        people: [{ id: "00000000-0000-4000-8000-0000000000a1", name: "에리" }],
        scenes: [{ id: "00000000-0000-4000-8000-0000000000b1", name: "기쁨" }],
        cells: [
          {
            id: "00000000-0000-4000-8000-0000000000c1",
            personId: "00000000-0000-4000-8000-0000000000a1",
            sceneId: "00000000-0000-4000-8000-0000000000b1",
            imageAssetId: "00000000-0000-4000-8000-0000000000d1",
            situationDescription: "합격 소식을 듣고 웃는다",
            unlockHint: "합격 발표 날",
            excludeFromChat: true,
          },
        ],
      },
      description: "표류한 선원들의 생존기",
      genreId: "genre-adventure",
      target: "all",
      hashtags: ["모험"],
      visibility: "public",
    });
  });

  it("maps a null profile image and unset optional storySetting fields to null", () => {
    const values = baseFormValues();
    values.profile.image = null;
    values.storySetting.userGoal = undefined;
    values.storySetting.rules = undefined;

    const payload = formToServer(values);

    expect(payload.thumbnailAssetId).toBeNull();
    expect(payload.userGoal).toBeNull();
    expect(payload.rules).toBeNull();
  });

  it("never sends developmentExample — the old free-text field is retired FE-side, and the key must stay absent (not null) so the server keeps the old column as a rollback safety net until the migration that drops it", () => {
    const payload = formToServer(baseFormValues());

    expect(payload).not.toHaveProperty("developmentExample");
  });

  it("maps an empty developmentExamples array through unchanged (existing 33 contents are all in this state)", () => {
    const values = baseFormValues();
    values.storySetting.developmentExamples = [];

    const payload = formToServer(values);

    expect(payload.developmentExamples).toEqual([]);
  });

  it("preserves worldSetting even when promptTemplate is custom, and always includes rules/userGoal/developmentExamples (template-independent)", () => {
    const values = baseFormValues();
    values.storySetting = {
      promptTemplate: "custom",
      worldSetting: "남겨둔 이전 세계관 텍스트",
      developmentExamples: [{ userLine: "사용자 메시지 예시", assistantLine: "스토리 응답 예시" }],
      userGoal: "커스텀 목표",
      defaultUserName: "",
      rules: "커스텀 규칙",
      customPrompt: "커스텀 프롬프트 본문",
    };

    const payload = formToServer(values);

    expect(payload.promptTemplate).toBe("custom");
    expect(payload.settingText).toBe("남겨둔 이전 세계관 텍스트");
    expect(payload.developmentExamples).toEqual([{ userLine: "사용자 메시지 예시", assistantLine: "스토리 응답 예시" }]);
    expect(payload.userGoal).toBe("커스텀 목표");
    expect(payload.rules).toBe("커스텀 규칙");
    expect(payload.customPrompt).toBe("커스텀 프롬프트 본문");
  });

  it("maps a null selected genre/target as-is", () => {
    const values = baseFormValues();
    values.registration.genre = null;
    values.registration.target = null;

    const payload = formToServer(values);

    expect(payload.genreId).toBeNull();
    expect(payload.target).toBeNull();
  });

  it("maps unset openingSituation/playGuide/unit to null", () => {
    const values = baseFormValues();
    const setup = requireFirst(values.startingSetups);
    setup.openingSituation = undefined;
    setup.playGuide = undefined;
    requireFirst(setup.stats).unit = undefined;

    const payload = formToServer(values);

    const firstSetup = requireFirst(payload.startingSetups);
    expect(firstSetup.openingMessage).toBeNull();
    expect(firstSetup.playguide).toBeNull();
    expect(requireFirst(firstSetup.statDefs).unit).toBeNull();
  });

  it("preserves startingSetups/statDefs array order as the wire's implicit order (no explicit order field)", () => {
    const values = baseFormValues();
    const firstSetup = requireFirst(values.startingSetups);
    const firstStat = requireFirst(firstSetup.stats);
    values.startingSetups = [
      { ...firstSetup, id: "second", name: "second" },
      { ...firstSetup, id: "first", name: "first" },
    ];
    requireFirst(values.startingSetups).stats = [
      { ...firstStat, id: "stat-b" },
      { ...firstStat, id: "stat-a" },
    ];

    const payload = formToServer(values);

    expect(payload.startingSetups.map((setup) => setup.id)).toEqual(["second", "first"]);
    expect(requireFirst(payload.startingSetups).statDefs.map((stat) => stat.id)).toEqual(["stat-b", "stat-a"]);
  });

  it("never sends the removed change direction or max change per turn keys, with or without a counter", () => {
    // 서버는 두 키를 더는 받지 않는다(와도 무시한다). 이 폼이 다시 싣기 시작하면 옛 계약으로 되돌아간 것이다.
    for (const perTurnDelta of [-1, null]) {
      const values = baseFormValues();
      requireFirst(requireFirst(values.startingSetups).stats).perTurnDelta = perTurnDelta;
      const stat = requireFirst(requireFirst(formToServer(values).startingSetups).statDefs);
      expect(stat).not.toHaveProperty("changeDirection");
      expect(stat).not.toHaveProperty("maxChangePerTurn");
    }
  });

  it("sends a stat's rules in order with trimmed conditions, and an empty list when there are none", () => {
    const values = baseFormValues();
    const stat = requireFirst(requireFirst(values.startingSetups).stats);
    expect(requireFirst(requireFirst(formToServer(values).startingSetups).statDefs)).toHaveProperty("rules", []);

    stat.rules = [
      { id: "rule-b", condition: "  사용자가 약속에 늦었다 ", delta: -3 },
      { id: "rule-a", condition: "사용자가 짐을 나눠 들었다", delta: 3 },
    ];
    expect(requireFirst(requireFirst(formToServer(values).startingSetups).statDefs).rules).toEqual([
      { id: "rule-b", condition: "사용자가 약속에 늦었다", delta: -3 },
      { id: "rule-a", condition: "사용자가 짐을 나눠 들었다", delta: 3 },
    ]);
  });

  it("sends only the finished rules while some are half written, so the rest of the draft still saves", () => {
    // 서버는 빈 조건·빈 증감·0·조건 100자 초과·상한 초과·같은 id 를 초안 저장째 거절한다 — 실으면 다른 칸의 수정까지 저장되지
    // 않는다. 키를 통째로 빼면 지웠다 되돌린 스탯이 서버에서 규칙 없이 다시 만들어지므로, 키는 두고 완성된 규칙만 고른다.
    const valid = { id: "rule-1", condition: "사용자가 약속을 지켰다", delta: 2 };
    const cases = [
      { rules: [{ ...valid, id: "blank", condition: "   " }, valid], sent: [valid] },
      { rules: [valid, { ...valid, id: "nan", delta: Number.NaN }], sent: [valid] },
      { rules: [{ ...valid, id: "zero", delta: 0 }, valid], sent: [valid] },
      { rules: [{ ...valid, id: "fraction", delta: 1.5 }, valid], sent: [valid] },
      { rules: [{ ...valid, id: "long", condition: "가".repeat(101) }, valid], sent: [valid] },
      { rules: [valid, { ...valid, delta: -4 }], sent: [valid] },
      { rules: [{ ...valid, condition: "  " }], sent: [] },
    ];
    for (const { rules, sent } of cases) {
      const values = baseFormValues();
      const setup = requireFirst(values.startingSetups);
      const stat = requireFirst(setup.stats);
      setup.stats = [{ ...stat, rules }, { ...stat, id: "stat-other", rules: [valid] }];
      const [partial, other] = requireFirst(formToServer(values).startingSetups).statDefs;
      expect(partial).toHaveProperty("rules", sent);
      expect(other).toHaveProperty("rules", [valid]);
    }
  });

  it("sends at most ten finished rules, counting from the top and skipping half-written ones", () => {
    const values = baseFormValues();
    const stat = requireFirst(requireFirst(values.startingSetups).stats);
    const finished = Array.from({ length: 11 }, (_, index) => ({
      id: `rule-${index}`,
      condition: `조건 ${index}`,
      delta: index + 1,
    }));
    stat.rules = [{ id: "draft", condition: "", delta: Number.NaN }, ...finished];
    const sent = requireFirst(requireFirst(formToServer(values).startingSetups).statDefs).rules;
    expect(sent).toEqual(finished.slice(0, 10));
  });

  it("still sends a rule whose delta is wider than the stat range — only publishing checks that", () => {
    const values = baseFormValues();
    const stat = requireFirst(requireFirst(values.startingSetups).stats);
    stat.min = 0;
    stat.max = 5;
    stat.rules = [{ id: "rule-1", condition: "사용자가 크게 다쳤다", delta: -9 }];
    expect(requireFirst(requireFirst(formToServer(values).startingSetups).statDefs).rules).toEqual(stat.rules);
  });

  it("always sends each starting setup's situation notes, even an empty list", () => {
    // 서버는 이 키가 없으면 그 시작설정의 노트를 그대로 둔다 — 빼면 지운 노트와 스탯 삭제로 함께 지운 조건이 남는다.
    const values = baseFormValues();
    const setup = requireFirst(values.startingSetups);
    expect(requireFirst(formToServer(values).startingSetups)).toHaveProperty("situationNotes", []);

    setup.situationNotes = [
      {
        id: "situation-1",
        name: "상영회 당일",
        content: "오늘은 가을 상영회 당일이다.",
        conditionRules: [{ kind: "rule", id: "r1", statId: "stat-1", operator: "<=", value: 0, nextOp: null }],
      },
    ];
    expect(requireFirst(formToServer(values).startingSetups).situationNotes).toEqual([
      {
        id: "situation-1",
        name: "상영회 당일",
        infoText: "오늘은 가을 상영회 당일이다.",
        conditionRules: [{ kind: "rule", id: "r1", statId: "stat-1", operator: "lte", threshold: 0, nextOp: null }],
      },
    ]);
  });

  it("always sends the four keyword note options, even at their defaults", () => {
    // 생략하면 서버가 기존 값을 그대로 둔다(옛 화면용 규칙) — 이 화면이 기본값으로 되돌린 것도 저장되려면 늘 보내야 한다.
    const values = baseFormValues();
    values.keywordNotes = [
      { ...requireFirst(values.keywordNotes), name: "", excludeKeywords: [], stickyTurns: 0, alwaysOn: false },
    ];

    const note = requireFirst(formToServer(values).keywordNotes);

    expect(note).toMatchObject({ name: "", excludeKeywords: [], stickyTurns: 0, alwaysOn: false });
    expect(Object.keys(note)).toEqual(
      expect.arrayContaining(["name", "excludeKeywords", "stickyTurns", "alwaysOn"]),
    );
  });

  it("sends keyword notes in form array order", () => {
    const values = baseFormValues();
    const first = requireFirst(values.keywordNotes);
    values.keywordNotes = [
      { ...first, id: "note-b" },
      { ...first, id: "note-a" },
    ];

    expect(formToServer(values).keywordNotes.map((note) => note.id)).toEqual(["note-b", "note-a"]);
  });

  it("maps a global keyword note scope to a null startingSetupId", () => {
    const values = baseFormValues();
    values.keywordNotes = [{ ...requireFirst(values.keywordNotes), scope: { kind: "global" } }];

    const payload = formToServer(values);

    expect(requireFirst(payload.keywordNotes).startingSetupId).toBeNull();
  });

  it("maps a startingSetup keyword note scope to its startingSetupId", () => {
    const values = baseFormValues();
    values.keywordNotes = [
      { ...requireFirst(values.keywordNotes), scope: { kind: "startingSetup", startingSetupId: "setup-9" } },
    ];

    const payload = formToServer(values);

    expect(requireFirst(payload.keywordNotes).startingSetupId).toBe("setup-9");
  });

  it("passes shortcuts through unchanged", () => {
    const payload = formToServer(baseFormValues());

    expect(payload.shortcuts).toEqual([
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ]);
  });

  it("maps an ending's rule tree (single rule + group) into the wire shape, including the operator rename", () => {
    const values = baseFormValues();
    requireFirst(values.startingSetups).endings = [
      {
        id: "ending-1",
        name: "함께 살아남기",
        turnGate: 12,
        judgePrompt: "주인공들이 서로를 구조했는지 판정",
        statRules: [
          { kind: "rule", id: "rule-1", statId: "stat-1", operator: ">=", value: 50, nextOp: "and" },
          {
            kind: "group",
            id: "group-1",
            nextOp: null,
            rules: [
              { kind: "rule", id: "rule-2", statId: "stat-2", operator: "<", value: 10, nextOp: "or" },
              { kind: "rule", id: "rule-3", statId: "stat-3", operator: "==", value: 3, nextOp: null },
            ],
          },
        ],
        epilogue: "두 사람은 무사히 구조되었다.",
        hint: "체력과 신뢰를 함께 관리하세요.",
        priorityStatId: "stat-2",
      },
    ];

    const payload = formToServer(values);

    expect(requireFirst(payload.startingSetups).endings).toEqual([
      {
        id: "ending-1",
        name: "함께 살아남기",
        turnCountGate: 12,
        judgmentPrompt: "주인공들이 서로를 구조했는지 판정",
        epilogue: "두 사람은 무사히 구조되었다.",
        hint: "체력과 신뢰를 함께 관리하세요.",
        statRules: [
          { kind: "rule", id: "rule-1", statId: "stat-1", operator: "gte", threshold: 50, nextOp: "and" },
          {
            kind: "group",
            id: "group-1",
            nextOp: null,
            rules: [
              { kind: "rule", id: "rule-2", statId: "stat-2", operator: "lt", threshold: 10, nextOp: "or" },
              { kind: "rule", id: "rule-3", statId: "stat-3", operator: "eq", threshold: 3, nextOp: null },
            ],
          },
        ],
        priorityStatId: "stat-2",
      },
    ]);
  });

  it("maps unset ending epilogue/hint to null", () => {
    const values = baseFormValues();
    requireFirst(values.startingSetups).endings = [
      {
        id: "ending-1",
        name: "열린 결말",
        turnGate: 10,
        judgePrompt: "판정 프롬프트",
        statRules: [],
        epilogue: undefined,
        hint: undefined,
        priorityStatId: null,
      },
    ];

    const payload = formToServer(values);

    const firstEnding = requireFirst(requireFirst(payload.startingSetups).endings);
    expect(firstEnding.epilogue).toBeNull();
    expect(firstEnding.hint).toBeNull();
  });

  // 서버는 빠진 우선순위 스탯을 "기존 값 유지"로 읽는다 — '없음'을 키째 빼면 작가가 비운 값이 저장되지 않는다.
  it("sends a cleared ending priority stat as an explicit null key, not an omitted one", () => {
    const values = baseFormValues();
    requireFirst(values.startingSetups).endings = [
      { id: "ending-1", name: "열린 결말", turnGate: 10, judgePrompt: "판정", statRules: [], priorityStatId: null },
    ];

    const firstEnding = requireFirst(requireFirst(formToServer(values).startingSetups).endings);

    expect(Object.hasOwn(firstEnding, "priorityStatId")).toBe(true);
    expect(firstEnding.priorityStatId).toBeNull();
  });

  it("preserves endings/statRules array order as the wire's implicit order (no explicit order field)", () => {
    const values = baseFormValues();
    const firstSetup = requireFirst(values.startingSetups);
    firstSetup.endings = [
      { id: "second", name: "second", turnGate: 10, judgePrompt: "판정", statRules: [], priorityStatId: null },
      { id: "first", name: "first", turnGate: 10, judgePrompt: "판정", statRules: [], priorityStatId: null },
    ];
    requireFirst(firstSetup.endings).statRules = [
      { kind: "rule", id: "rule-b", statId: "stat-1", operator: ">", value: 1, nextOp: null },
      { kind: "rule", id: "rule-a", statId: "stat-1", operator: ">", value: 1, nextOp: null },
    ];

    const payload = formToServer(values);

    const firstPayloadSetup = requireFirst(payload.startingSetups);
    expect(firstPayloadSetup.endings.map((ending) => ending.id)).toEqual(["second", "first"]);
    expect(requireFirst(firstPayloadSetup.endings).statRules.map((rule) => rule.id)).toEqual([
      "rule-b",
      "rule-a",
    ]);
  });
  // 표시 전용 값이 페이로드에 섞이면 서버 계약 밖 필드가 된다(서버는 조용히 버리므로 다른 테스트로는 안 드러난다).
  it("never sends the display-only image url/width/height of a media book cell", () => {
    const cell = requireFirst(formToServer(baseFormValues()).mediaBook?.cells ?? []);

    expect(cell).not.toHaveProperty("imageUrl");
    expect(cell).not.toHaveProperty("imageWidth");
    expect(cell).not.toHaveProperty("imageHeight");
  });

  it("sends an empty media book explicitly so removing the last cell and axis reaches the server", () => {
    const values = baseFormValues();
    values.mediaBook = { people: [], scenes: [], cells: [] };

    expect(formToServer(values).mediaBook).toEqual({ people: [], scenes: [], cells: [] });
  });

  // 서버는 `mediaBook` 이 없으면 미디어 북에 손대지 않는다. 서버가 거절할 미디어 북을 실으면 PATCH 전체가 422 가
  // 돼 다른 탭의 수정까지 저장되지 않으므로, 그동안은 미디어 북만 빼고 나머지는 그대로 보낸다.
  it.each([
    ["an empty person name", (values: StoryBuilderFormValues) => (values.mediaBook.people = [{ id: PERSON_ID, name: "" }])],
    [
      "a person name over 20 characters",
      (values: StoryBuilderFormValues) => (values.mediaBook.people = [{ id: PERSON_ID, name: "가".repeat(21) }]),
    ],
    [
      "two scenes with the same name",
      (values: StoryBuilderFormValues) =>
        values.mediaBook.scenes.push({ id: "00000000-0000-4000-8000-0000000000b2", name: "기쁨" }),
    ],
    ["an axis id that is not a uuid", (values: StoryBuilderFormValues) => (values.mediaBook.people = [{ id: "person-1", name: "에리" }])],
  ])("omits the media book but keeps every other field when it has %s", (_label, mutate) => {
    const values = baseFormValues();
    mutate(values);

    const payload = formToServer(values);

    expect(payload).not.toHaveProperty("mediaBook");
    const validPayload = formToServer(baseFormValues());
    delete validPayload.mediaBook;
    expect(payload).toEqual(validPayload);
  });
  // 자동저장은 폼 검증을 거치지 않는다. 서버가 거절할 이름을 실으면 PATCH 전체가 422 가 되어 다른 칸까지 저장되지 않는다.
  it("leaves out a default user name the server would reject, so the rest of the draft still saves", () => {
    for (const name of ["별*", "{{user}}", "가".repeat(21)]) {
      const values = baseFormValues();
      values.storySetting.defaultUserName = name;
      expect(formToServer(values)).not.toHaveProperty("defaultUserName");
    }
  });

  // 서버도 앞뒤 공백을 걷어 저장한다. 미리보기는 보낸 값을 그대로 이름으로 쓰므로 여기서 걷지 않으면 미리보기 화면과
  // 서버 프롬프트의 이름이 갈린다. 공백만 있으면 빈 값이 돼 서버처럼 대체어로 돌아간다.
  it("sends a valid or empty default user name trimmed, like the server stores it", () => {
    for (const [name, sent] of [
      ["", ""],
      ["조수", "조수"],
      [" 조수 ", "조수"],
      ["   ", ""],
    ] as const) {
      const values = baseFormValues();
      values.storySetting.defaultUserName = name;
      expect(formToServer(values).defaultUserName).toBe(sent);
    }
  });
});
