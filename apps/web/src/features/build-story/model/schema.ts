import { z } from "zod";

/**
 * techspec-builder-story.md §1 — `promptTemplate`이 'custom'일 때 `worldSetting`/`developmentExample`은
 * 화면 전환처럼 값은 폼 상태에 보존하되 검증에서만 제외하고, customPrompt를 필수로 요구한다.
 * 'basic'/'emotional'/'simulation'일 때는 반대로 worldSetting을 필수로 요구하고 customPrompt는 제외한다.
 * developmentExample(고급설정)은 어느 템플릿에서도 필수가 아니다.
 */
export const storySettingSchema = z
  .object({
    promptTemplate: z.enum(["basic", "emotional", "simulation", "custom"]).default("basic"),
    worldSetting: z.string().optional(),
    developmentExample: z.string().optional(),
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

/** techspec-builder-story.md §1.2 — 시작설정별 독립 스탯. */
export const statDefSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  icon: z.string(),
  color: z.string(),
  min: z.number(),
  max: z.number(),
  initial: z.number(),
  unit: z.string().optional(),
  description: z.string().min(1),
});

/**
 * techspec-builder-story.md §1.5 — `shared/lib/rule-engine`의 `SingleRule`/`RuleGroup`/`RuleListItem`과
 * 구조적으로 동일한 값을 생성한다(재정의가 아니라 재사용 — `formToServer.ts`/`serverToForm.ts`가 이
 * 스키마의 추론 타입을 그 타입들의 함수 시그니처에 그대로 대입해 컴파일타임에 어긋남을 잡아낸다).
 * `operator`는 실제 DB enum(`EndingRuleOperator`: gte/lte/eq/gt/lt, techspec-db-schema.md §5)에 맞춰
 * `ComparisonOp`의 6개 값 중 서버가 애초에 저장할 방법이 없는 "!="만 제외한 5개로 좁힌다.
 * 그룹(`ruleGroupSchema`)의 `rules`는 `singleRuleSchema`만 허용해 그룹 중첩을 zod 레벨에서 막는다(FR-59).
 */
const comparisonOpSchema = z.enum([">", ">=", "<", "<=", "=="]);
const logicOpSchema = z.enum(["and", "or"]);

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

/** techspec-builder-story.md §1.5 — turnGate는 최소 10턴(선행 게이트), statRules가 비어있으면 judgePrompt만으로 판정한다(FR-58). */
export const endingSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  turnGate: z.number().min(10),
  judgePrompt: z.string().min(1),
  statRules: z.array(ruleListItemSchema).default([]),
  epilogue: z.string().optional(),
  hint: z.string().optional(),
});

/**
 * techspec-builder-story.md §1.1 — 시작설정 배열은 dnd-kit로 재정렬 가능하며, 목록의 첫 번째
 * 항목이 기본 선택이다.
 */
export const startingSetupSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  prologue: z.string().min(1),
  openingSituation: z.string().optional(),
  playGuide: z.string().optional(),
  suggestedReplies: z.array(z.string()).default([]),
  stats: z.array(statDefSchema).default([]),
  endings: z.array(endingSchema).default([]),
});

/** techspec-builder-story.md §1.3 — scope는 discriminated union, 서버는 nullable startingSetupId FK로 저장한다. */
export const keywordNoteSchema = z.object({
  id: z.string(),
  content: z.string().min(1),
  triggerKeywords: z.array(z.string().min(1)).min(1),
  scope: z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("global") }),
    z.object({ kind: z.literal("startingSetup"), startingSetupId: z.string() }),
  ]),
});

/** techspec-builder-story.md §1.4. */
export const shortcutSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  description: z.string().min(1),
  prompt: z.string().min(1),
});

export const storyBuilderSchema = z.object({
  profile: z.object({
    name: z.string().min(1),
    oneLiner: z.string().min(1),
    image: z.object({ assetId: z.string() }).nullable(),
  }),
  storySetting: storySettingSchema,
  startingSetups: z.array(startingSetupSchema).min(1),
  keywordNotes: z.array(keywordNoteSchema).default([]),
  shortcuts: z.array(shortcutSchema).default([]),
  registration: z.object({
    description: z.string().min(1),
    // 실제 StoryDraftPayload/Response의 genreId/target 계약(string|null / ContentTarget|null)에 맞춰
    // profile.image와 동일한 이유로 nullable로 둔다(US-091 캐릭터 빌더와 동일한 판단 — 초안 상태에선
    // 아직 선택 전일 수 있고, 발행 시 필수 검증은 이 스키마를 쓰는 이후 빌더 UI 스토리의 몫이다).
    genre: z.string().nullable(),
    target: z.enum(["female", "male", "all"]).nullable(),
    hashtags: z.array(z.string()).default([]),
    visibility: z.enum(["public", "link", "private"]).default("private"),
  }),
});

export type StorySettingValues = z.infer<typeof storySettingSchema>;
export type StatDefValues = z.infer<typeof statDefSchema>;
export type RuleListItemValues = z.infer<typeof ruleListItemSchema>;
export type SingleRuleValues = Extract<RuleListItemValues, { kind: "rule" }>;
export type EndingValues = z.infer<typeof endingSchema>;
export type StartingSetupValues = z.infer<typeof startingSetupSchema>;
export type KeywordNoteValues = z.infer<typeof keywordNoteSchema>;
export type ShortcutValues = z.infer<typeof shortcutSchema>;
export type StoryBuilderFormValues = z.infer<typeof storyBuilderSchema>;
