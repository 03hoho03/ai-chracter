import { z } from "zod";

// 목록과 유니온 타입은 한쪽에서 도출한다. 값 목록을 스키마 옆의 단일 소스로 두고
// widgets/build-story/ui/RegistrationTab.tsx가 이 배열을 map해 라벨만 매핑한다(손복사 금지).
export const TARGET_VALUES = ["female", "male", "all"] as const;
export type Target = (typeof TARGET_VALUES)[number];

export const VISIBILITY_VALUES = ["public", "link", "private"] as const;
export type Visibility = (typeof VISIBILITY_VALUES)[number];

/**
 * 전개 예시 한 쌍. build-character의
 * `exampleDialogueSchema`와 같은 입출력 쌍 모양이지만 `id`는 두지 않는다 — 서버 계약
 * (`DevelopmentExampleItem`)에 id가 없고(다른 레코드가 참조하지 않고 순서가 곧 정체성), id를 넣으면
 * `serverToForm`이 매번 새 id를 발급해야 해서 순수 함수가 아니게 된다. 위젯에서 목록 key가 필요하면
 * RHF가 `useFieldArray`에 자동으로 붙여주는 `field.id`를 쓴다(등록된 폼 필드가 아니라 값에 섞이지 않는다).
 */
export const developmentExampleSchema = z.object({
  userLine: z.string(),
  assistantLine: z.string(),
});

/**
 * `promptTemplate`이 'custom'일 때 `worldSetting`은 화면 전환처럼
 * 값은 폼 상태에 보존하되 검증에서만 제외하고, customPrompt를 필수로 요구한다.
 * 'basic'/'emotional'/'simulation'일 때는 반대로 worldSetting을 필수로 요구하고 customPrompt는 제외한다.
 * `developmentExamples`/`userGoal`/`rules`는 템플릿과 무관하게
 * 항상 적용되는 L1 작품 층이라 이 분기 대상이 아니고, 어느 템플릿에서도 필수가 아니다
 * (기존 33건이 비어 있는 채로 발행돼 있다).
 */
// widgets/build-story/ui/SettingTab.tsx의 PROMPT_TEMPLATE_LABELS가 이 배열을 단일 소스로
// 삼는다(라벨·설명 문구만 위젯이 map해 붙인다).
export const PROMPT_TEMPLATE_VALUES = ["basic", "emotional", "simulation", "custom"] as const;
export type PromptTemplate = (typeof PROMPT_TEMPLATE_VALUES)[number];

export const storySettingSchema = z
  .object({
    promptTemplate: z.enum(PROMPT_TEMPLATE_VALUES).default("basic"),
    worldSetting: z.string().optional(),
    developmentExamples: z
      .array(developmentExampleSchema)
      .max(3, "전개 예시는 최대 3개까지만 추가할 수 있습니다")
      .default([]),
    userGoal: z.string().optional(),
    rules: z.string().optional(),
    customPrompt: z.string().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.promptTemplate === "custom") {
      if (!value.customPrompt || value.customPrompt.length < 1) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["customPrompt"],
          message: "커스텀 프롬프트를 입력해 주세요.",
        });
      }
      return;
    }
    if (!value.worldSetting || value.worldSetting.length < 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["worldSetting"],
        message: "세계관 설정을 입력해 주세요.",
      });
    }
  });

/** 시작설정별 독립 스탯. */
export const statDefSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "스탯 이름을 입력해주세요"),
  icon: z.string().min(1, "아이콘을 선택해주세요"),
  color: z.string().min(1, "색상을 선택해주세요"),
  min: z.number(),
  max: z.number(),
  initial: z.number(),
  unit: z.string().optional(),
  description: z.string().min(1, "스탯에 대한 설명을 입력해주세요"),
  /** 매 턴 자동으로 더해지는 값(감소는 음수). 비우면 판정 LLM이 이 스탯을 판단한다. */
  perTurnDelta: z.number().int().optional(),
});

/**
 * `entities/chat-room`의 `SingleRule`/`RuleGroup`/`RuleListItem`과
 * 구조적으로 동일한 값을 생성한다(재사용이 아니라 독자 선언 — 두 타입을 잇는 컴파일타임 검사는 없고
 * 모양만 맞춰 둔다. `formToServer.ts`/`serverToForm.ts`는 생성 DTO(`EndingRuleDraftItem`)와만 대응한다).
 * `operator`는 실제 DB enum(`EndingRuleOperator`: gte/lte/eq/gt/lt)에 맞춰
 * `ComparisonOp`의 6개 값 중 서버가 애초에 저장할 방법이 없는 "!="만 제외한 5개로 좁힌다.
 * 그룹(`ruleGroupSchema`)의 `rules`는 `singleRuleSchema`만 허용해 그룹 중첩을 zod 레벨에서 막는다.
 */
// widgets/build-story/ui/EndingTab.tsx가 이 두 배열을 단일 소스로 삼는다(손복사 금지).
export const COMPARISON_OPERATORS = [">", ">=", "<", "<=", "=="] as const;
export const LOGIC_OPERATORS = ["and", "or"] as const;

const comparisonOpSchema = z.enum(COMPARISON_OPERATORS);
const logicOpSchema = z.enum(LOGIC_OPERATORS);

const singleRuleSchema = z.object({
  kind: z.literal("rule"),
  id: z.string(),
  statId: z.string(),
  operator: comparisonOpSchema,
  value: z.number(),
  nextOp: logicOpSchema.nullable(),
});

const ruleGroupSchema = z.object({
  kind: z.literal("group"),
  id: z.string(),
  rules: z.array(singleRuleSchema),
  nextOp: logicOpSchema.nullable(),
});

export const ruleListItemSchema = z.discriminatedUnion("kind", [singleRuleSchema, ruleGroupSchema]);

/** turnGate는 최소 10턴(선행 게이트), statRules가 비어있으면 judgePrompt만으로 판정한다. */
export const endingSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "엔딩 이름을 입력해주세요"),
  turnGate: z.number().min(10, "엔딩조건은 10턴 이상이어야 합니다"),
  judgePrompt: z.string().min(1, "이 엔딩에 도달했는지 AI가 판단할 기준을 입력해주세요"),
  statRules: z.array(ruleListItemSchema).default([]),
  epilogue: z.string().optional(),
  hint: z.string().optional(),
});

/** 상한 값의 단일 소스. 스키마의 `.max()`와 메시지,
 * widgets/build-story/ui/StartingSetupTab.tsx의 라벨 표기·추가 버튼 게이트가 전부 여기를 읽는다
 * (같은 숫자를 두 번 적으면 한쪽만 고치고 끝난다). */
export const MAX_STARTING_SETUPS = 4;
export const MAX_SUGGESTED_REPLIES = 4;

/**
 * 시작설정 배열은 dnd-kit로 재정렬 가능하며, 목록의 첫 번째
 * 항목이 기본 선택이다.
 */
export const startingSetupSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "시작설정 이름을 입력해주세요"),
  prologue: z.string().min(1, "이 시작설정의 도입부를 입력해주세요"),
  openingSituation: z.string().optional(),
  playGuide: z.string().optional(),
  suggestedReplies: z
    .array(z.string())
    // 사용자 문구는 화면 라벨과 같은 "추천 답변"이다(식별자만 서버 계약의 suggestedReplies를 따른다).
    .max(MAX_SUGGESTED_REPLIES, `추천 답변은 최대 ${MAX_SUGGESTED_REPLIES}개까지만 추가할 수 있습니다`)
    .default([]),
  stats: z.array(statDefSchema).default([]),
  endings: z.array(endingSchema).default([]),
});

/** scope는 discriminated union, 서버는 nullable startingSetupId FK로 저장한다. */
export const keywordNoteSchema = z.object({
  id: z.string(),
  content: z.string().min(1, "정보를 입력해주세요"),
  triggerKeywords: z
    .array(z.string().min(1, "키워드를 입력해주세요"))
    .min(1, "트리거 키워드를 1개 이상 추가해주세요"),
  scope: z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("global") }),
    z.object({ kind: z.literal("startingSetup"), startingSetupId: z.string() }),
  ]),
});

export const shortcutSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "단축어 이름을 입력해주세요"),
  description: z.string().min(1, "이 단축어가 어떤 동작을 하는지 설명해주세요"),
  prompt: z.string().min(1, "단축어 실행 시 AI에게 전달할 프롬프트를 입력해주세요"),
});

/** 서버가 422 로 막는 미디어 북 상한의 단일 소스. 스키마의 `.max()`와 메시지가 여기를 읽는다. */
export const MAX_MEDIA_BOOK_CELLS = 50;
export const MAX_MEDIA_BOOK_NAME_LENGTH = 20;
const MAX_MEDIA_BOOK_SITUATION_LENGTH = 100;
const MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH = 20;
// 본문 태그 `{{img::인물/장면}}`의 구분자들. 이름에 들어가면 태그를 인물·장면으로 가를 수 없다.
const MEDIA_BOOK_NAME_FORBIDDEN = /[/{}:]/;

// 축·칸·자산 id 는 서버가 uuid 로 받는다. `z.uuid()`는 RFC 변형 비트까지 요구해 서버가 받는 id 도 거절할 수
// 있어, 서버(파이썬 `uuid.UUID`)처럼 16진 8-4-4-4-12 모양만 보는 `z.guid()`를 쓴다.
const mediaBookIdSchema = z.guid("미디어 북 항목의 id 가 올바르지 않습니다");

/** 서버가 이름을 비교·저장하는 형태(앞뒤 공백 제거 + NFC). 길이와 중복을 이 값으로 잰다. */
function normalizeMediaBookName(value: string): string {
  return value.trim().normalize("NFC");
}

// 서버는 글자 수를 코드 포인트로 센다 — `.length`(UTF-16)로 세면 이모지가 두 글자가 돼 서버가 받는
// 길이를 폼이 먼저 막는다.
function countCharacters(value: string): number {
  return [...value].length;
}

/**
 * 미디어 북 축(인물·장면) 항목. 서버는 앞뒤 공백을 지우고 NFC 로 맞춘 뒤 길이를 재고 저장하므로, 폼도 같은
 * 정규화 결과로 길이를 잰다 — 값 자체는 바꾸지 않는다(정규화된 이름은 저장 응답이 돌려준다).
 */
export const mediaBookAxisSchema = z.object({
  id: mediaBookIdSchema,
  name: z
    .string()
    .refine((value) => countCharacters(normalizeMediaBookName(value)) >= 1, "이름을 입력해주세요")
    .refine(
      (value) => countCharacters(normalizeMediaBookName(value)) <= MAX_MEDIA_BOOK_NAME_LENGTH,
      `이름은 ${MAX_MEDIA_BOOK_NAME_LENGTH}자 이하로 입력해주세요`,
    )
    .refine((value) => !MEDIA_BOOK_NAME_FORBIDDEN.test(value), "이름에는 / { } : 를 쓸 수 없습니다"),
});

/**
 * 미디어 북 칸 하나(인물 × 장면 자리에 이미지 1장). `personId`/`sceneId`는 축 항목의 `id`다.
 * `imageUrl`/`imageWidth`/`imageHeight`는 화면 표시 전용이라 `formToServer`가 서버로 보내지 않는다.
 */
export const mediaBookCellSchema = z.object({
  id: mediaBookIdSchema,
  personId: mediaBookIdSchema,
  sceneId: mediaBookIdSchema,
  imageAssetId: mediaBookIdSchema,
  imageUrl: z.string().optional(),
  imageWidth: z.number().optional(),
  imageHeight: z.number().optional(),
  situationDescription: z
    .string()
    .refine(
      (value) => countCharacters(value) <= MAX_MEDIA_BOOK_SITUATION_LENGTH,
      `상황 설명은 ${MAX_MEDIA_BOOK_SITUATION_LENGTH}자 이하로 입력해주세요`,
    ),
  unlockHint: z
    .string()
    .refine(
      (value) => countCharacters(value) <= MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH,
      `해금 힌트는 ${MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH}자 이하로 입력해주세요`,
    ),
  excludeFromChat: z.boolean(),
});

/**
 * 미디어 북 전체. 서버가 422 로 막는 페이로드 규칙(칸 상한, 같은 축 안 id·이름 중복, 칸이 가리키는 축의 존재,
 * 같은 인물 × 장면 칸 중복, 칸 id 중복)을 모두 여기서도 검사한다 — `formToServer`가 이 스키마를 통과하지 못한
 * 미디어 북을 자동저장에서 빼는 기준이라, 서버가 거절할 값이 이 스키마를 통과하면 그 초안 저장 전체가 막힌다.
 */
export const mediaBookSchema = z.object({
  people: z.array(mediaBookAxisSchema),
  scenes: z.array(mediaBookAxisSchema),
  cells: z
    .array(mediaBookCellSchema)
    .max(MAX_MEDIA_BOOK_CELLS, `미디어 북 이미지는 최대 ${MAX_MEDIA_BOOK_CELLS}장까지만 넣을 수 있습니다`),
})
  .superRefine((value, ctx) => {
    for (const axis of ["people", "scenes"] as const) {
      const seenIds = new Set<string>();
      const seenNames = new Set<string>();
      value[axis].forEach((item, index) => {
        if (seenIds.has(item.id)) {
          ctx.addIssue({ code: "custom", path: [axis, index, "id"], message: "같은 id 의 항목이 두 번 들어 있습니다" });
        }
        seenIds.add(item.id);
        const name = normalizeMediaBookName(item.name);
        if (seenNames.has(name)) {
          ctx.addIssue({ code: "custom", path: [axis, index, "name"], message: "같은 이름이 이미 있습니다" });
        }
        seenNames.add(name);
      });
    }
    const personIds = new Set(value.people.map((person) => person.id));
    const sceneIds = new Set(value.scenes.map((scene) => scene.id));
    const seenCellIds = new Set<string>();
    const seenPositions = new Set<string>();
    value.cells.forEach((cell, index) => {
      if (seenCellIds.has(cell.id)) {
        ctx.addIssue({ code: "custom", path: ["cells", index, "id"], message: "같은 id 의 칸이 두 번 들어 있습니다" });
      }
      seenCellIds.add(cell.id);
      // 축 참조에는 서버 FK 가 없어 서버가 페이로드 안에서 이 검사를 한다 — 같은 규칙을 폼에도 둔다.
      if (!personIds.has(cell.personId) || !sceneIds.has(cell.sceneId)) {
        ctx.addIssue({ code: "custom", path: ["cells", index], message: "칸이 가리키는 인물이나 장면이 없습니다" });
      }
      // uuid 모양 id 에는 `|` 가 없어 이어 붙인 키가 서로 다른 자리끼리 겹치지 않는다.
      const position = `${cell.personId}|${cell.sceneId}`;
      if (seenPositions.has(position)) {
        ctx.addIssue({ code: "custom", path: ["cells", index], message: "한 칸에는 이미지를 한 장만 넣을 수 있습니다" });
      }
      seenPositions.add(position);
    });
  });

export const storyBuilderSchema = z.object({
  profile: z.object({
    name: z.string().min(1, "스토리 이름을 입력해주세요"),
    oneLiner: z.string().min(1, "스토리를 한 줄로 소개해주세요"),
    // 타입은 초안(아직 비어 있는 상태)을 담기 위해 nullable로 두고, 발행 필수는 superRefine이 상시
    // 검증한다. **`.refine((v) => v !== null)`으로 줄이지
    // 말 것** — TS 5.5+가 그 콜백을 타입 술어로 추론하고 zod의 refine 선언이 그 경우에만 출력 타입을
    // 좁혀(zod/v4/classic/schemas.d.cts:38) `z.infer`에서 null이 사라진다(serverToForm이 깨졌다).
    // superRefine 선언은 조건 없이 `this`다(같은 파일 39행).
    image: z
      .object({ assetId: z.string() })
      .nullable()
      .superRefine((value, ctx) => {
        if (value === null) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, message: "대표 이미지를 등록해주세요" });
        }
      }),
  }),
  storySetting: storySettingSchema,
  startingSetups: z
    .array(startingSetupSchema)
    .min(1, "시작설정을 1개 이상 추가해주세요")
    .max(MAX_STARTING_SETUPS, `시작설정은 최대 ${MAX_STARTING_SETUPS}개까지만 추가할 수 있습니다`),
  keywordNotes: z.array(keywordNoteSchema).default([]),
  shortcuts: z.array(shortcutSchema).default([]),
  mediaBook: mediaBookSchema,
  registration: z.object({
    description: z.string().min(1, "스토리를 목록에서 소개할 설명을 입력해주세요"),
    // 실제 StoryDraftPayload/Response의 genreId/target 계약(string|null / ContentTarget|null)에 맞춰
    // profile.image와 동일한 이유로 nullable로 둔다(캐릭터 빌더와 동일한 판단 — 초안 상태에선
    // 아직 선택 전일 수 있다). 발행 필수는 profile.image와 같은 이유·같은 방식(superRefine)으로 상시
    // 검증한다(`.refine`을 쓰지 않는 이유는 profile.image 주석에 있다).
    genre: z
      .string()
      .nullable()
      .superRefine((value, ctx) => {
        if (value === null) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, message: "장르를 선택해주세요" });
        }
      }),
    target: z
      .enum(TARGET_VALUES)
      .nullable()
      .superRefine((value, ctx) => {
        if (value === null) {
          ctx.addIssue({ code: z.ZodIssueCode.custom, message: "타겟을 선택해주세요" });
        }
      }),
    hashtags: z.array(z.string()).default([]),
    visibility: z.enum(VISIBILITY_VALUES).default("private"),
  }),
});

export type StorySettingValues = z.infer<typeof storySettingSchema>;
export type DevelopmentExampleValues = z.infer<typeof developmentExampleSchema>;
export type StatDefValues = z.infer<typeof statDefSchema>;
export type RuleListItemValues = z.infer<typeof ruleListItemSchema>;
export type SingleRuleValues = Extract<RuleListItemValues, { kind: "rule" }>;
export type EndingValues = z.infer<typeof endingSchema>;
export type StartingSetupValues = z.infer<typeof startingSetupSchema>;
export type KeywordNoteValues = z.infer<typeof keywordNoteSchema>;
export type ShortcutValues = z.infer<typeof shortcutSchema>;
export type MediaBookAxisValues = z.infer<typeof mediaBookAxisSchema>;
export type MediaBookCellValues = z.infer<typeof mediaBookCellSchema>;
export type MediaBookValues = z.infer<typeof mediaBookSchema>;
export type StoryBuilderFormValues = z.infer<typeof storyBuilderSchema>;
