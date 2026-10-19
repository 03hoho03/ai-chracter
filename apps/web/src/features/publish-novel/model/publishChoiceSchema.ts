import { z } from "zod";

import { countCharacters } from "@/shared/lib/text/characterCount";

import type { PublishChoice } from "./publicationView";

/** 변경 요약 상한. 서버 상수와 같은 값이다 — 상태 응답이 상한을 싣지 않아 화면에 사본을 둔다(서버가 바꾸면 함께
 * 바꾼다. 어긋나면 서버가 422 로 막는다). */
export const CHANGE_SUMMARY_MAX_LENGTH = 100;

/** 공개 모달 폼 — 끝 화, 새 화 중 가격을 고르는 화마다 무료인가, 다시 내는 고친 화마다 변경 요약. 가격·요약 칸은 노벨
 * 정책 스위치가 켜졌을 때만 채운다(꺼지면 빈 배열이라 검증할 것이 없다).
 *
 * 변경 요약은 서버와 같은 규칙이다 — 앞뒤 공백을 덜고 1자 이상, 상한은 코드 포인트로 센다. 입력칸에 `maxLength` 를 두지
 * 않는다 — 붙여넣은 글이 말없이 잘리지 않고 오류로 보이게. */
export const publishChoiceSchema = z.object({
  targetOrdinal: z.number(),
  prices: z.array(z.object({ ordinal: z.number(), isFree: z.boolean() })),
  summaries: z.array(
    z.object({
      ordinal: z.number(),
      text: z
        .string()
        .trim()
        .min(1, { message: "바뀐 것을 적어 주세요" })
        .refine((value) => countCharacters(value) <= CHANGE_SUMMARY_MAX_LENGTH, {
          message: `${CHANGE_SUMMARY_MAX_LENGTH}자 이내로 적어 주세요`,
        }),
    }),
  ),
});

export type PublishChoiceFormInput = z.input<typeof publishChoiceSchema>;
export type PublishChoiceFormValues = z.output<typeof publishChoiceSchema>;

/** 폼 값 → 모달이 돌려줄 선택. 가격 줄은 고를 수 있는 끝까지 미리 만들어 두므로 고른 끝 화 뒤의 줄은 버린다. */
export function toPublishChoice(values: PublishChoiceFormValues): PublishChoice {
  return {
    targetOrdinal: values.targetOrdinal,
    freeByOrdinal: Object.fromEntries(
      values.prices.filter((price) => price.ordinal <= values.targetOrdinal).map((price) => [price.ordinal, price.isFree]),
    ),
    changeSummaries: Object.fromEntries(values.summaries.map((summary) => [summary.ordinal, summary.text])),
  };
}
