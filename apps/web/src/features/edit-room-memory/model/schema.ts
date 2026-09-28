import { zodResolver } from "@hookform/resolvers/zod";
import type { UseFormProps } from "react-hook-form";
import { z } from "zod";

import type { ChatRoomMemory } from "@/entities/chat-room";

/** 서버가 세는 방식 그대로의 글자 수 — 앞뒤 공백을 잘라낸 뒤 코드 포인트 수. JS `.length`는 UTF-16 단위라
 * 이모지 같은 문자를 2자로 세서 서버가 받는 입력을 막게 된다. 카운터도 이 값을 보인다. */
export function countMemoryChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 기억 패널 폼 하나가 두 칸을 함께 든다. 저장은 칸마다 따로다(서버 경로와 동시성 규칙이 다르다 — 노트는
 * 버전 검사 없이 덮어쓰고, 요약은 폼을 연 시점의 버전으로 검사한다).
 *
 * 상한은 서버 응답의 `limits`에서 받는다 — BE 상수의 사본을 두지 않는다. 규칙은 BE 요청 스키마와 같다:
 * 앞뒤 공백을 잘라낸 뒤 0자 이상 상한 이하(빈 칸 저장 허용), 글자는 코드 포인트로 센다. 입력칸에
 * `maxLength`를 두지 않고 여기서 막는 이유는 붙여넣기가 조용히 잘리지 않게 하기 위해서다. */
export function createMemoryFormSchema(limits: ChatRoomMemory["limits"]) {
  return z.object({
    note: z
      .string()
      .trim()
      .refine((value) => countMemoryChars(value) <= limits.noteMaxLength, {
        message: `${limits.noteMaxLength}자 이내로 적어 주세요`,
      }),
    summary: z
      .string()
      .trim()
      .refine((value) => countMemoryChars(value) <= limits.summaryMaxLength, {
        message: `${limits.summaryMaxLength}자 이내로 적어 주세요`,
      }),
  });
}

export type MemoryFormValues = z.infer<ReturnType<typeof createMemoryFormSchema>>;

/** 폼의 검증 옵션. 두 칸의 [저장]은 각각 `handleSubmit`으로 폼 전체를 검증한다 — 그래서 요약을 고치는 중에
 * 요약 칸이 상한을 넘기면 노트 저장도 막히고, 노트 칸이 넘치면 요약 저장도 막힌다(오류는 넘친 칸에 보인다).
 * 검증 시점은 기본값이다: [저장]을 누르기 전에는 입력마다 검증하지 않고, 한 번 누른 뒤부터는 입력마다 다시
 * 검증해 글자를 지워 상한 아래로 내리면 오류가 곧바로 풀린다. */
export function memoryFormOptions(
  schema: ReturnType<typeof createMemoryFormSchema>,
): Pick<UseFormProps<MemoryFormValues>, "resolver"> {
  return { resolver: zodResolver(schema) };
}
