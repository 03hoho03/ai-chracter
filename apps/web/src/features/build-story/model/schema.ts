import { z } from "zod";

import { normalizeMediaBookName } from "@/entities/media-book";
import { defaultUserNameIssue } from "@/entities/persona";

// 목록과 유니온 타입은 한쪽에서 도출한다. 값 목록을 스키마 옆의 단일 소스로 두고
// 화면 글자는 fieldOptions.ts 가 값마다 붙인다(손복사 금지).
export const TARGET_VALUES = ["female", "male", "all"] as const;
export type Target = (typeof TARGET_VALUES)[number];

export const VISIBILITY_VALUES = ["public", "link", "private"] as const;
export type Visibility = (typeof VISIBILITY_VALUES)[number];

/** 전개 예시 개수 상한. 스키마의 `.max()`와 빌더의 라벨 표기·추가 버튼 게이트가 함께 읽는다. */
export const MAX_DEVELOPMENT_EXAMPLES = 3;

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
// fieldOptions.ts 의 PROMPT_TEMPLATE_LABELS 가 이 배열을 단일 소스로 삼는다(라벨·설명 문구만 값마다 붙인다).
export const PROMPT_TEMPLATE_VALUES = ["basic", "emotional", "simulation", "custom"] as const;
export type PromptTemplate = (typeof PROMPT_TEMPLATE_VALUES)[number];

export const storySettingSchema = z
  .object({
    promptTemplate: z.enum(PROMPT_TEMPLATE_VALUES).default("basic"),
    worldSetting: z.string().optional(),
    developmentExamples: z
      .array(developmentExampleSchema)
      .max(MAX_DEVELOPMENT_EXAMPLES, `전개 예시는 최대 ${MAX_DEVELOPMENT_EXAMPLES}개까지만 추가할 수 있습니다`)
      .default([]),
    userGoal: z.string().optional(),
    // 사용자의 역할 옆에 두는 작품 기본 이름. 대화 프로필이 없는 사람의 `{{user}}` 가 된다. 비우면 대체어를 쓴다.
    defaultUserName: z
      .string()
      .superRefine((value, ctx) => {
      const issue = defaultUserNameIssue(value);
      if (issue !== null) ctx.addIssue({ code: "custom", message: issue });
    })
      .default(""),
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

/** 스탯 규칙 상한의 단일 소스(서버 상한과 같은 값). 스키마의 검사·메시지와 스탯 탭의 입력 가드가 전부 여기를 읽는다. 자동저장은
 * 이 스키마를 거치지 않으므로 개수 상한은 입력 단계에서 막는다 — 넘는 목록이 폼에 들어가면 서버가 그 초안의 저장을 통째로
 * 거절한다. 조건 길이는 서버처럼 앞뒤 공백을 뗀 뒤 코드 포인트로 센다. */
export const MAX_STAT_RULES = 10;
export const MAX_STAT_RULE_CONDITION_LENGTH = 100;
export const STAT_RULE_LIMIT_MESSAGE = `규칙은 스탯마다 ${MAX_STAT_RULES}개까지예요. 더 넣으려면 쓰지 않는 규칙을 지워 주세요.`;
export const STAT_RULE_DELTA_MESSAGE = "0이 아닌 정수로 입력해주세요(예: +3, -5)";

/**
 * 턴당 자동 변화가 있는 스탯은 판정 AI 가 보지 않아 규칙이 발동할 일이 없다 — 서버는 둘을 함께 건 스탯의 발행을 거절한다. 스탯
 * 탭은 한쪽을 채우면 다른 쪽을 잠그므로 이 상태는 다른 기기·옛 데이터에서만 들어온다.
 */
export const STAT_RULES_WITH_COUNTER_MESSAGE = "턴당 자동 변화와 규칙은 함께 쓸 수 없어요. 한쪽을 비워 주세요.";

/** 규칙 폭이 스탯 범위 폭을 넘을 때의 문장. 서버는 저장은 받고 발행만 막는다(범위를 좁힌 뒤에도 자동저장이 돌게). */
export function statRuleDeltaTooWideMessage(rangeWidth: number): string {
  return `폭은 이 스탯의 범위 폭(${rangeWidth}) 이하여야 해요. 그보다 크면 한 번에 반대쪽 끝을 넘어가요.`;
}

/**
 * 스탯 하나의 「조건 → 증감」 규칙. 판정 AI 가 이번 턴에 맞은 규칙을 고르면 코드가 폭의 절댓값이 가장 큰 하나(같으면 목록
 * 앞)만 더한다 — 순서가 동점의 우선순위라 배열 위치가 곧 순서다. 증감 칸이 비었거나 정수로 읽히지 않으면 NaN 이다.
 */
export const statRuleSchema = z.object({
  id: z.string(),
  condition: z
    .string()
    .refine((value) => value.trim().length > 0, "조건을 입력해주세요")
    .refine(
      (value) => countCharacters(value.trim()) <= MAX_STAT_RULE_CONDITION_LENGTH,
      `조건은 ${MAX_STAT_RULE_CONDITION_LENGTH}자 이하로 입력해주세요`,
    ),
  delta: z
    .number({ error: STAT_RULE_DELTA_MESSAGE })
    .int(STAT_RULE_DELTA_MESSAGE)
    .refine((value) => value !== 0, STAT_RULE_DELTA_MESSAGE),
});

/** 초안 저장이 받는 규칙 목록 — 서버가 422 로 막는 조건(개수·조건 길이·폭 0·같은 스탯 안 id 중복)을 그대로 건다. 발행 전
 * 폼 검증이 이 스키마로 칸마다 오류를 붙인다. 자동저장은 목록째 거르지 않고 `formToServer` 가 규칙 하나씩 `statRuleSchema` 로
 * 골라 보낸다. 폭이 범위 폭을 넘는지는 발행만 본다. */
export const statRulesSchema = z
  .array(statRuleSchema)
  .max(MAX_STAT_RULES, STAT_RULE_LIMIT_MESSAGE)
  .superRefine((rules, ctx) => {
    const seen = new Set<string>();
    rules.forEach((rule, index) => {
      if (seen.has(rule.id)) {
        ctx.addIssue({ code: "custom", path: [index, "id"], message: "같은 id 의 규칙이 두 번 들어 있습니다" });
      }
      seen.add(rule.id);
    });
  });

/** 턴당 자동 변화 칸에 숫자가 들어 있는가(빈 칸은 null, 다 지우지 못한 칸은 NaN). */
export function hasPerTurnDelta(stat: Pick<StatDefValues, "perTurnDelta">): boolean {
  return stat.perTurnDelta !== null && Number.isFinite(stat.perTurnDelta);
}

/**
 * 시작설정별 독립 스탯.
 *
 * 최소·최대·초기값 칸은 `valueAsNumber` 로 등록돼 빈 칸이 NaN 으로 들어온다. zod 는 NaN 을 타입 오류로 보고 영어 기본
 * 문구를 내므로 칸마다 한국어 문구를 직접 준다. 타입 오류는 이후 검사를 멈추게 해서, 빈 칸이 있으면 아래 범위 검사는 돌지
 * 않는다(NaN 비교로 엉뚱한 범위 오류가 붙지 않는다).
 *
 * 범위 검사는 오류를 문제의 칸에 붙인다 — StatTab 이 칸마다 자기 경로의 메시지를 그린다. 최소·최대가 뒤집혀 있으면 최대값
 * 칸만 알린다. 그 상태에서 초기값 문구("100~0 사이")는 뜻이 없다. 서버는 같은 규칙을 발행 때만 본다(초안 자동저장은 이미
 * 저장된 모순 초안도 받아야 하므로) — 이 검사가 정상 화면 흐름에서 먼저 막는다.
 */
/** 스탯 수치 네 칸(최소·최대·초기값, 턴당 변화)은 서버가 정수로만 받는다 — 소수를 넣으면 초안 자동저장부터 거절된다. */
const STAT_INTEGER_MESSAGE = "정수로 입력해주세요";

export const statDefSchema = z
  .object({
    id: z.string(),
    name: z.string().min(1, "스탯 이름을 입력해주세요"),
    icon: z.string().min(1, "아이콘을 선택해주세요"),
    color: z.string().min(1, "색상을 선택해주세요"),
    min: z.number({ error: "최소값을 입력해주세요" }).int(STAT_INTEGER_MESSAGE),
    max: z.number({ error: "최대값을 입력해주세요" }).int(STAT_INTEGER_MESSAGE),
    initial: z.number({ error: "초기값을 입력해주세요" }).int(STAT_INTEGER_MESSAGE),
    unit: z.string().optional(),
    description: z.string().min(1, "스탯에 대한 설명을 입력해주세요"),
    /**
     * 매 턴 자동으로 더해지는 값(감소는 음수). 비우면 판정 LLM이 이 스탯을 판단한다(규칙이 있으면 규칙으로).
     *
     * 빈 값은 `undefined` 가 아니라 `null` 이고 키를 빼지 못하게 둔다. RHF 는 폼 값이 `undefined` 인 칸이 마운트될 때 같은
     * 경로의 `defaultValues`(초안을 불러올 때의 값, 지우거나 추가해도 인덱스가 밀리지 않는다)로 채운다. 그래서 새 스탯이
     * 같은 자리에 있던 옛 스탯의 값을 물려받고, 비운 칸이 탭을 오갈 때 옛 값으로 되살아난다.
     */
    perTurnDelta: z.number().int(STAT_INTEGER_MESSAGE).nullable(),
    /** 「조건 → 증감」 규칙. 변화 방향·한 턴 최대 폭은 폼이 다루지 않는다 — 보내지 않으면 서버가 저장된 값을 그대로 둔다
     * (규칙이 없는 시작설정이 아직 쓰는 옛 판정 경로가 그 값을 읽는다). 보내는 예외는 `formToServer` 의 스탯 변환이 적는다. */
    rules: statRulesSchema,
    /**
     * 옛 화면이 저장한 0 이하의 한 턴 최대 폭. 서버는 이 값이 있으면 발행을 막는데(1 이상이어야 한다) 지금 화면에는 그 칸이
     * 없어 작가가 고칠 길이 없다. 그래서 불러올 때 이 값을 화면에 보이지 않는 채로 들고 있다가 `formToServer` 가 "제한
     * 없음"(null)을 보내 지운다. 그 밖의 스탯(새 스탯 포함)에는 키가 없다. 입력칸에 등록하지 않는 값이라 RHF 가 옛
     * `defaultValues` 로 다시 채우는 일이 없어 빈 값을 `undefined` 로 둔다.
     */
    legacyMaxChangePerTurn: z.number().optional(),
  })
  .superRefine((stat, ctx) => {
    // 오류는 턴당 자동 변화 칸에 붙인다 — 발행 때 이 스탯을 열고 그 칸으로 포커스가 가, 바로 아래 문장이 이유를 말한다.
    if (hasPerTurnDelta(stat) && stat.rules.length > 0) {
      ctx.addIssue({ code: "custom", path: ["perTurnDelta"], message: STAT_RULES_WITH_COUNTER_MESSAGE });
    }
    if (stat.max <= stat.min) {
      ctx.addIssue({ code: "custom", path: ["max"], message: "최대값은 최소값보다 커야 해요" });
      return;
    }
    if (stat.initial < stat.min || stat.initial > stat.max) {
      ctx.addIssue({
        code: "custom",
        path: ["initial"],
        message: `초기값은 ${stat.min}~${stat.max} 사이여야 해요`,
      });
    }
    // 최소 < 최대일 때만 잰다(뒤집힌 범위는 위에서 돌아간다). 초기값이 범위 밖이어도 폭은 최소·최대만으로 정해지므로 잰다.
    // 서버 발행 검사는 뒤집힌 범위에서도 재어 `stats.range` 와 함께 `stats.ruleDelta` 를 내지만, 그때의 폭(0 이하)은 뜻이 없어
    // 최대값 칸 오류 하나만 보인다 — 범위를 고치면 이 검사가 다시 돌아 서버와 같은 규칙을 짚는다. 폭 칸에 붙여 그 규칙 줄로
    // 포커스가 간다.
    const rangeWidth = stat.max - stat.min;
    stat.rules.forEach((rule, index) => {
      if (Math.abs(rule.delta) > rangeWidth) {
        ctx.addIssue({ code: "custom", path: ["rules", index, "delta"], message: statRuleDeltaTooWideMessage(rangeWidth) });
      }
    });
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
  /**
   * 같은 턴에 조건을 넘은 엔딩이 여럿일 때 비교할 같은 시작설정의 스탯 id. 이 칸을 정한 엔딩끼리는 각자 고른 스탯 값이 가장
   * 높은 엔딩만 판정한다. 빈 값(목록 순서대로 판정)은 `null` 이고 키를 빼지 못하게 둔다 — 이유는 스탯의 `perTurnDelta` 와
   * 같다(RHF 가 `undefined` 칸을 같은 자리 옛 엔딩의 값으로 다시 채운다). 비어 있어도 발행할 수 있는 선택 칸이다.
   */
  priorityStatId: z.string().nullable(),
});

/** 조건 수. 그룹 자체는 세지 않고 그 안의 조건을 센다 — 서버가 상황 노트의 조건 상한·"조건 없음"을 따지는 셈과 같다. */
export function countRules(items: readonly RuleListItemValues[]): number {
  return items.reduce((sum, item) => sum + (item.kind === "group" ? item.rules.length : 1), 0);
}

/** 상황 노트 상한의 단일 소스(서버 상한과 같은 값). 스키마의 검사·메시지와 widgets/build-story 의 상황 노트 탭·조건 편집기의
 * 입력 가드가 전부 여기를 읽는다. 자동저장은 이 스키마를 거치지 않으므로 상한은 입력 단계에서 막아야 한다 — 넘는 값이 폼에
 * 들어가면 서버가 그 초안의 저장을 통째로 거절한다. */
export const MAX_SITUATION_NOTES = 10;
export const MAX_SITUATION_NOTE_NAME_LENGTH = 20;
export const MAX_SITUATION_NOTE_CONTENT_LENGTH = 800;
export const MAX_SITUATION_NOTE_RULES = 10;
export const SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE = "조건을 하나 이상 넣어 주세요";
export const SITUATION_NOTE_BLANK_CONTENT_MESSAGE = "상황을 입력해주세요";
export const SITUATION_NOTE_RULE_LIMIT_MESSAGE = `조건은 노트마다 ${MAX_SITUATION_NOTE_RULES}개까지예요(그룹 안 조건 포함).`;

/**
 * 시작설정마다 둘 수 있는 상황 노트. 조건(엔딩 스탯 규칙과 같은 규칙 목록)이 참인 턴에 본문이 이야기를 쓰는 AI 에게 실린다.
 * 순서는 배열 위치다. 본문 이름은 키워드 노트 폼과 같은 `content`(서버는 `infoText`).
 *
 * 조건 없음·본문 공백은 서버가 저장은 받고 발행만 막는다(노트를 막 추가한 초안도 저장돼야 한다). 이 스키마는 발행 때만
 * 돌므로 같은 두 검사를 여기 둬 발행 버튼이 그 노트의 칸을 바로 짚게 한다. 빈 그룹만 있는 노트도 조건 0개다(서버와 같은 셈).
 */
export const situationNoteSchema = z.object({
  id: z.string(),
  name: z
    .string()
    .refine(
      (value) => countCharacters(value) <= MAX_SITUATION_NOTE_NAME_LENGTH,
      `이름은 ${MAX_SITUATION_NOTE_NAME_LENGTH}자 이하로 입력해주세요`,
    ),
  content: z
    .string()
    .refine((value) => value.trim().length > 0, SITUATION_NOTE_BLANK_CONTENT_MESSAGE)
    .refine(
      (value) => countCharacters(value) <= MAX_SITUATION_NOTE_CONTENT_LENGTH,
      `상황은 ${MAX_SITUATION_NOTE_CONTENT_LENGTH}자 이하로 입력해주세요`,
    ),
  conditionRules: z.array(ruleListItemSchema).superRefine((rules, ctx) => {
    const count = countRules(rules);
    if (count === 0) ctx.addIssue({ code: "custom", message: SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE });
    else if (count > MAX_SITUATION_NOTE_RULES) ctx.addIssue({ code: "custom", message: SITUATION_NOTE_RULE_LIMIT_MESSAGE });
  }),
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
  situationNotes: z
    .array(situationNoteSchema)
    .max(MAX_SITUATION_NOTES, `상황 노트는 시작설정마다 최대 ${MAX_SITUATION_NOTES}개까지만 추가할 수 있습니다`)
    .default([]),
});

/** 키워드북 상한의 단일 소스. 스키마의 검사·메시지와 widgets/build-story/ui/KeywordNoteTab.tsx 의 입력 가드가 전부
 * 여기를 읽는다. 자동저장은 이 스키마를 거치지 않고 폼 값을 그대로 보내므로, 서버가 거절할 값은 입력 단계에서부터
 * 폼에 들어가지 않아야 한다(들어가면 그 초안의 자동저장이 통째로 멈춘다). */
export const MAX_KEYWORD_NOTES = 50;
export const MAX_KEYWORD_NOTE_CONTENT_LENGTH = 800;
export const MAX_TRIGGER_KEYWORDS = 10;
export const MAX_TRIGGER_KEYWORD_LENGTH = 20;
export const TRIGGER_KEYWORD_BLANK_MESSAGE = "키워드를 입력해주세요";
export const TRIGGER_KEYWORD_TOO_LONG_MESSAGE = `키워드는 ${MAX_TRIGGER_KEYWORD_LENGTH}자 이하로 입력해주세요`;
export const TRIGGER_KEYWORD_LIMIT_MESSAGE = `트리거 키워드는 최대 ${MAX_TRIGGER_KEYWORDS}개까지만 추가할 수 있습니다`;
export const TRIGGER_KEYWORD_DUPLICATE_MESSAGE = "같은 키워드가 이미 있어요(영문 대소문자는 구분하지 않아요)";
// 금지 키워드는 트리거 키워드와 같은 개수·길이·정규화 규칙을 쓴다(서버도 같은 검사를 두 목록에 건다).
export const MAX_EXCLUDE_KEYWORDS = MAX_TRIGGER_KEYWORDS;
export const EXCLUDE_KEYWORD_LIMIT_MESSAGE = `금지 키워드는 최대 ${MAX_EXCLUDE_KEYWORDS}개까지만 추가할 수 있습니다`;
export const MAX_KEYWORD_NOTE_NAME_LENGTH = 20;
export const MAX_KEYWORD_NOTE_STICKY_TURNS = 5;
export const MAX_ALWAYS_ON_KEYWORD_NOTES = 3;

/**
 * 키워드 중복을 가리는 비교 키. 서버는 NFC 로 맞춘 뒤 파이썬 `casefold()` 로 접어 비교하는데 JS 에는 casefold 가
 * 없다. 소문자화만 하면 서버보다 느슨해(예: `ß`·`ẞ` 는 서버에서 `ss` 와 같다) 서버만 중복으로 보는 값을 폼이
 * 받아 자동저장이 거절된다. 소문자 → 대문자 → 소문자를 거치면 casefold 가 접는 모든 코드 포인트가 같은 키로
 * 모인다(전 코드 포인트 대조로 확인 — 소문자화만으로는 101개가 어긋났다). 반대로 폼이 더 엄격한 경우(점 없는
 * `ı` 와 `i` 등)는 서버가 받을 값을 폼이 막을 뿐이라 자동저장을 멈추지 않는다.
 */
export function normalizeKeyword(value: string): string {
  return value.normalize("NFC").toLowerCase().toUpperCase().toLowerCase();
}

/**
 * 키워드 칩 목록(트리거·금지 공용). 원소 하나의 위반도 배열 자리에 싣는다 — 화면은 키워드 목록 아래 한 줄로만 오류를
 * 보여 준다. "1개 이상"은 여기 두지 않는다 — 트리거 키워드만, 그것도 상시가 아닌 노트에만 요구한다(노트 스키마).
 */
function keywordListSchema(limitMessage: string) {
  return z
    .array(z.string())
    .max(MAX_TRIGGER_KEYWORDS, limitMessage)
    .superRefine((keywords, ctx) => {
      const seen = new Set<string>();
      for (const keyword of keywords) {
        if (keyword.trim().length === 0) {
          ctx.addIssue({ code: "custom", message: TRIGGER_KEYWORD_BLANK_MESSAGE });
          return;
        }
        if (countCharacters(keyword) > MAX_TRIGGER_KEYWORD_LENGTH) {
          ctx.addIssue({ code: "custom", message: TRIGGER_KEYWORD_TOO_LONG_MESSAGE });
          return;
        }
        const key = normalizeKeyword(keyword);
        if (seen.has(key)) {
          ctx.addIssue({ code: "custom", message: TRIGGER_KEYWORD_DUPLICATE_MESSAGE });
          return;
        }
        seen.add(key);
      }
    });
}

/**
 * scope는 discriminated union, 서버는 nullable startingSetupId FK로 저장한다.
 *
 * 상시(`alwaysOn`) 노트는 키워드 없이 매 턴 실리므로 트리거 키워드 1개 이상을 요구하지 않는다. 금지 키워드는 상시
 * 노트에도 걸린다(금지 키워드가 나온 턴에는 상시 노트도 빠진다). 이름은 목록에서 노트를 알아보는 용도라 AI 에게
 * 보내지 않는다.
 */
export const keywordNoteSchema = z
  .object({
    id: z.string(),
    content: z
      .string()
      .min(1, "정보를 입력해주세요")
      .refine(
        (value) => countCharacters(value) <= MAX_KEYWORD_NOTE_CONTENT_LENGTH,
        `정보는 ${MAX_KEYWORD_NOTE_CONTENT_LENGTH}자 이하로 입력해주세요`,
      ),
    triggerKeywords: keywordListSchema(TRIGGER_KEYWORD_LIMIT_MESSAGE),
    scope: z.discriminatedUnion("kind", [
      z.object({ kind: z.literal("global") }),
      z.object({ kind: z.literal("startingSetup"), startingSetupId: z.string() }),
    ]),
    name: z
      .string()
      .refine(
        (value) => countCharacters(value) <= MAX_KEYWORD_NOTE_NAME_LENGTH,
        `이름은 ${MAX_KEYWORD_NOTE_NAME_LENGTH}자 이하로 입력해주세요`,
      ),
    excludeKeywords: keywordListSchema(EXCLUDE_KEYWORD_LIMIT_MESSAGE),
    stickyTurns: z.number().int().min(0).max(MAX_KEYWORD_NOTE_STICKY_TURNS),
    alwaysOn: z.boolean(),
  })
  .superRefine((note, ctx) => {
    if (!note.alwaysOn && note.triggerKeywords.length === 0) {
      ctx.addIssue({ code: "custom", path: ["triggerKeywords"], message: "트리거 키워드를 1개 이상 추가해주세요" });
    }
  });

/** "노트 추가"가 넣는 새 노트. 옵션은 서버가 새 노트에 주는 기본값과 같다. */
export function createKeywordNote(id: string): KeywordNoteValues {
  return {
    id,
    content: "",
    triggerKeywords: [],
    scope: { kind: "global" },
    name: "",
    excludeKeywords: [],
    stickyTurns: 0,
    alwaysOn: false,
  };
}

export const shortcutSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "단축어 이름을 입력해주세요"),
  description: z.string().min(1, "이 단축어가 어떤 동작을 하는지 설명해주세요"),
  prompt: z.string().min(1, "단축어 실행 시 AI에게 전달할 프롬프트를 입력해주세요"),
});

/** 서버가 422 로 막는 미디어 북 상한의 단일 소스. 스키마의 `.max()`와 메시지가 여기를 읽는다. */
export const MAX_MEDIA_BOOK_CELLS = 50;
export const MAX_MEDIA_BOOK_NAME_LENGTH = 20;
export const MAX_MEDIA_BOOK_SITUATION_LENGTH = 100;
export const MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH = 20;
// 같은 축 안 이름 중복 문구. 이름 입력 칸(`mediaBookNameError`)과 스키마 검사가 같은 문장을 내도록 여기 하나만 둔다.
export const MEDIA_BOOK_DUPLICATE_NAME_MESSAGE = "같은 이름이 이미 있어요";
// 본문 태그 `{{img::인물/장면}}`의 구분자들. 이름에 들어가면 태그를 인물·장면으로 가를 수 없다.
const MEDIA_BOOK_NAME_FORBIDDEN = /[/{}:]/;

// 축·칸·자산 id 는 서버가 uuid 로 받는다. `z.uuid()`는 RFC 변형 비트까지 요구해 서버가 받는 id 도 거절할 수
// 있어, 서버(파이썬 `uuid.UUID`)처럼 16진 8-4-4-4-12 모양만 보는 `z.guid()`를 쓴다.
const mediaBookIdSchema = z.guid("미디어 북 항목의 id 가 올바르지 않습니다");

// 서버는 글자 수를 코드 포인트로 센다 — `.length`(UTF-16)로 세면 이모지가 두 글자가 돼 서버가 받는
// 길이를 폼이 먼저 막는다.
export function countCharacters(value: string): number {
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
          ctx.addIssue({ code: "custom", path: [axis, index, "name"], message: MEDIA_BOOK_DUPLICATE_NAME_MESSAGE });
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
  keywordNotes: z
    .array(keywordNoteSchema)
    .max(MAX_KEYWORD_NOTES, `키워드 노트는 최대 ${MAX_KEYWORD_NOTES}개까지만 추가할 수 있습니다`)
    // 배열 자리 오류라 키워드북 탭 머리의 한 줄에 보인다.
    .superRefine((notes, ctx) => {
      if (notes.filter((note) => note.alwaysOn).length > MAX_ALWAYS_ON_KEYWORD_NOTES) {
        ctx.addIssue({
          code: "custom",
          message: `상시 적용 노트는 최대 ${MAX_ALWAYS_ON_KEYWORD_NOTES}개까지만 켤 수 있습니다`,
        });
      }
    })
    .default([]),
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
export type StatRuleValues = z.infer<typeof statRuleSchema>;
export type RuleListItemValues = z.infer<typeof ruleListItemSchema>;
export type SingleRuleValues = Extract<RuleListItemValues, { kind: "rule" }>;
export type EndingValues = z.infer<typeof endingSchema>;
export type SituationNoteValues = z.infer<typeof situationNoteSchema>;
export type StartingSetupValues = z.infer<typeof startingSetupSchema>;
export type KeywordNoteValues = z.infer<typeof keywordNoteSchema>;
export type ShortcutValues = z.infer<typeof shortcutSchema>;
export type MediaBookAxisValues = z.infer<typeof mediaBookAxisSchema>;
export type MediaBookCellValues = z.infer<typeof mediaBookCellSchema>;
export type MediaBookValues = z.infer<typeof mediaBookSchema>;
export type StoryBuilderFormValues = z.infer<typeof storyBuilderSchema>;
