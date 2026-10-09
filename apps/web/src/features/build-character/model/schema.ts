import { z } from "zod";

import {
  characterLimit,
  DEFAULT_NOVEL_PERMISSION,
  hashtagsSchema,
  MAX_CHARACTER_PROMPT_LENGTH,
  MAX_DESCRIPTION_LENGTH,
  MAX_EXAMPLE_DIALOGUE_LINE_LENGTH,
  MAX_EXAMPLE_DIALOGUES,
  MAX_INTRO_LENGTH,
  MAX_NAME_LENGTH,
  MAX_ONE_LINER_LENGTH,
  MAX_PLAY_GUIDE_LENGTH,
  MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH,
  NOVEL_PERMISSION_VALUES,
} from "@/entities/content";

// 목록과 유니온 타입은 한쪽에서 도출한다. 값 목록을 스키마 옆의 단일 소스로 두고
// widgets/build-character/ui/DetailTab.tsx가 이 배열을 map해 라벨만 매핑한다(손복사 금지).
export const TARGET_VALUES = ["female", "male", "all"] as const;
export type Target = (typeof TARGET_VALUES)[number];

export const VISIBILITY_VALUES = ["public", "link", "private"] as const;
export type Visibility = (typeof VISIBILITY_VALUES)[number];

export const exampleDialogueSchema = z.object({
  id: z.string(),
  userLine: z
    .string()
    .min(1, "사용자 대사를 입력해주세요")
    .refine(...characterLimit(MAX_EXAMPLE_DIALOGUE_LINE_LENGTH, "사용자 대사")),
  characterLine: z
    .string()
    .min(1, "캐릭터 대사를 입력해주세요")
    .refine(...characterLimit(MAX_EXAMPLE_DIALOGUE_LINE_LENGTH, "캐릭터 대사")),
});

/** 상황별 이미지는 배열 순서 자체가 동시매칭 우선순위다. */
export const situationalImageSchema = z.object({
  id: z.string(),
  // 업로드/AI생성 갤러리 선택 모두 assetId 참조로 수렴한다 — 업로드 중
  // 상태는 이미지 필드 컴포넌트의 로컬 상태로만 존재하고 이 스키마에는 두지 않는다.
  image: z.object({ assetId: z.string() }).nullable(),
  situationDescription: z
    .string()
    .min(1, "어떤 상황에서 이 이미지를 노출할지 입력해주세요")
    .refine((value) => value.trim().length > 0, "어떤 상황에서 이 이미지를 노출할지 입력해주세요")
    .refine(...characterLimit(MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH, "상황")),
});

export const characterBuilderSchema = z.object({
  profile: z.object({
    // 대표 이미지가 맨 앞인 이유: 발행 실패 때 포커스가 가는 "첫 오류"는 같은 탭 안에서 이 키 순서를 따른다. 화면에서 맨 위 칸이
    // 대표 이미지라 순서가 다르면 둘째 칸(이름)으로 먼저 간다.
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
    name: z.string().min(1, "캐릭터 이름을 입력해주세요").refine(...characterLimit(MAX_NAME_LENGTH, "이름")),
    oneLiner: z
      .string()
      .min(1, "캐릭터를 한 줄로 소개해주세요")
      .refine(...characterLimit(MAX_ONE_LINER_LENGTH, "한줄소개")),
  }),
  intro: z.object({
    firstMessage: z
      .string()
      .min(1, "사용자와의 첫 대화에서 캐릭터가 건넬 말을 입력해주세요")
      .refine(...characterLimit(MAX_INTRO_LENGTH, "인트로")),
    exampleDialogues: z
      .array(exampleDialogueSchema)
      .max(MAX_EXAMPLE_DIALOGUES, `예시 대화는 최대 ${MAX_EXAMPLE_DIALOGUES}개까지만 추가할 수 있습니다`)
      .default([]),
    playGuide: z.string().refine(...characterLimit(MAX_PLAY_GUIDE_LENGTH, "플레이가이드")).optional(),
    // 입력칸은 없다. 저장된 작품 기본 이름을 미리보기 시작 요청에 그대로 실으려고 폼에 둔다. 보이지 않는 값이라
    // 발행을 막지 않도록 검사하지 않고, 규칙에 어긋난 옛 값은 서버로 보낼 때 빠진다.
    defaultUserName: z.string().default(""),
  }),
  prompt: z.object({
    characterPrompt: z
      .string()
      .min(1, "캐릭터의 성격, 말투, 배경 등을 자유롭게 서술해주세요")
      .refine(...characterLimit(MAX_CHARACTER_PROMPT_LENGTH, "캐릭터 프롬프트")),
  }),
  situationalImages: z.array(situationalImageSchema).default([]),
  registration: z.object({
    description: z
      .string()
      .min(1, "캐릭터를 목록에서 소개할 설명을 입력해주세요")
      .refine(...characterLimit(MAX_DESCRIPTION_LENGTH, "등록 설명")),
    // CharacterDraftPayload/Response의 genreId/target은 실제로 string | null / ContentTarget | null이다
    // (초안 상태에선 아직 선택 전일 수 있음) — profile.image와 동일한 이유로 nullable로 둔다. 발행
    // 필수는 profile.image와 같은 이유·같은 방식(superRefine)으로 상시 검증한다
    // (`.refine`을 쓰지 않는 이유는 profile.image 주석에 있다).
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
    hashtags: hashtagsSchema,
    visibility: z.enum(VISIBILITY_VALUES).default("private"),
    novelPermission: z.enum(NOVEL_PERMISSION_VALUES).default(DEFAULT_NOVEL_PERMISSION),
  }),
});

export type CharacterBuilderFormValues = z.infer<typeof characterBuilderSchema>;
export type ExampleDialogueValues = z.infer<typeof exampleDialogueSchema>;
export type SituationalImageValues = z.infer<typeof situationalImageSchema>;
