import { z } from "zod";

import { countChapterChars } from "./chapterBody";

/** AI 수정 지시 폼. 서버와 같은 규칙이다 — 앞뒤 공백을 걷고 1자 이상, 상한은 상세가 준 값(코드 포인트로 센다).
 * 입력칸에 `maxLength` 를 두지 않는다 — 붙여넣은 글이 말없이 잘리지 않고 오류로 보이게. */
export function createAiEditInstructionSchema(maxLength: number) {
  return z.object({
    instruction: z
      .string()
      .trim()
      .min(1, { message: "어떻게 고칠지 적어주세요" })
      .refine((value) => countChapterChars(value) <= maxLength, {
        message: `${maxLength.toLocaleString()}자 이내로 적어주세요`,
      }),
  });
}

export type AiEditInstructionFormValues = z.infer<ReturnType<typeof createAiEditInstructionSchema>>;

/** 지시 창의 자주 쓰는 요청 칩. 누르면 지시 칸을 이 글로 채운다 — 이용자가 직접 적은 것과 똑같은 지시로 가고 서버·모델 쪽
 * 글은 바뀌지 않는다. 그래서 글은 모델에 거는 명령이 아니라 이용자가 쓸 법한 부탁이다. "직접 적기"는 칸을 비우고 입력으로
 * 보낸다. */
export const AI_EDIT_KIND_CHIPS = [
  { label: "묘사 더하기", text: "장면이 눈앞에 그려지도록 묘사를 더해 주세요." },
  { label: "문체 다듬기", text: "뜻은 그대로 두고 문장을 매끄럽게 다듬어 주세요." },
  { label: "대사 고치기", text: "대사를 더 자연스럽고 인물답게 고쳐 주세요." },
  { label: "줄이기", text: "내용은 살리고 더 짧게 줄여 주세요." },
  { label: "직접 적기", text: "" },
] as const;
