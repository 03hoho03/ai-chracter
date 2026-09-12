import { z } from "zod";

// TS-09 — 목록과 유니온 타입은 한쪽에서 도출한다. 값 목록을 스키마 옆의 단일 소스로 두고
// widgets/build-character/ui/DetailTab.tsx가 이 배열을 map해 라벨만 매핑한다(손복사 금지).
export const TARGET_VALUES = ["female", "male", "all"] as const;
export type Target = (typeof TARGET_VALUES)[number];

export const VISIBILITY_VALUES = ["public", "link", "private"] as const;
export type Visibility = (typeof VISIBILITY_VALUES)[number];

export const exampleDialogueSchema = z.object({
  id: z.string(),
  userLine: z.string().min(1, "사용자 대사를 입력해주세요"),
  characterLine: z.string().min(1, "캐릭터 대사를 입력해주세요"),
});

/** techspec-builder-character.md §2 — 상황별 이미지는 배열 순서 자체가 동시매칭 우선순위다(§2 참고). */
export const situationalImageSchema = z.object({
  id: z.string(),
  // 업로드/AI생성 갤러리 선택 모두 assetId 참조로 수렴한다(techspec-overview.md §8.1) — 업로드 중
  // 상태는 이미지 필드 컴포넌트의 로컬 상태로만 존재하고 이 스키마에는 두지 않는다.
  image: z.object({ assetId: z.string() }).nullable(),
  situationDescription: z
    .string()
    .min(1, "어떤 상황에서 이 이미지를 노출할지 입력해주세요")
    .refine((value) => value.trim().length > 0, "어떤 상황에서 이 이미지를 노출할지 입력해주세요"),
});

export const characterBuilderSchema = z.object({
  profile: z.object({
    name: z.string().min(1, "캐릭터 이름을 입력해주세요"),
    oneLiner: z.string().min(1, "캐릭터를 한 줄로 소개해주세요"),
    image: z.object({ assetId: z.string() }).nullable(),
  }),
  intro: z.object({
    firstMessage: z.string().min(1, "사용자와의 첫 대화에서 캐릭터가 건넬 말을 입력해주세요"),
    exampleDialogues: z.array(exampleDialogueSchema).default([]),
    playGuide: z.string().optional(),
  }),
  prompt: z.object({
    characterPrompt: z.string().min(1, "캐릭터의 성격, 말투, 배경 등을 자유롭게 서술해주세요"),
  }),
  situationalImages: z.array(situationalImageSchema).default([]),
  registration: z.object({
    description: z.string().min(1, "캐릭터를 목록에서 소개할 설명을 입력해주세요"),
    // CharacterDraftPayload/Response의 genreId/target은 실제로 string | null / ContentTarget | null이다
    // (초안 상태에선 아직 선택 전일 수 있음) — profile.image와 동일한 이유로 nullable로 둔다. 발행 시
    // 필수 여부를 강제하는 검증은 이 스키마를 소비하는 빌더 UI 스토리(발행 버튼 연동)의 몫이다.
    genre: z.string().nullable(),
    target: z.enum(TARGET_VALUES).nullable(),
    hashtags: z.array(z.string()).default([]),
    visibility: z.enum(VISIBILITY_VALUES).default("private"),
  }),
});

export type CharacterBuilderFormValues = z.infer<typeof characterBuilderSchema>;
export type ExampleDialogueValues = z.infer<typeof exampleDialogueSchema>;
export type SituationalImageValues = z.infer<typeof situationalImageSchema>;
