import type { components } from "@ai-character-chat/api-types";

import type { GenerateImagesFormValues } from "./schema";

/** `POST /images/generate` 바디. DTO를 그대로 쓰지 못하고 model·style 두 축만 넓힌다 —
 * 폼은 그 둘을 `GET /images/models` 응답에서 받은 문자열로 들고 있는데(LT-9 / IR-10, 스키마도
 * `z.string().min(1)`이다) DTO는 `model: "v1"` 상수와 `ImageStylePreset` 7종 리터럴이라 정적으로
 * 맞출 방법이 없다. 좁히려면 `as`(fe-typescript 금지)를 쓰거나 FE가 스타일 목록을 하드코딩해야
 * 하는데, 후자는 "서버가 스타일 목록의 소스다"(IR-10)를 깨서 서버가 스타일을 늘리면 FE가 막는다.
 * 그 두 축의 검증은 서버가 하고, **나머지 세 축(prompt·aspectRatio·count)은 DTO에 묶여 있어**
 * 서버가 이름이나 모양을 바꾸면 컴파일이 깨진다. */
export type GenerateImageRequestBody = Omit<
  components["schemas"]["GenerateImageRequest"],
  "model" | "style"
> & {
  model: string;
  style: string;
};

/** 폼값 -> `POST /images/generate` 바디 (순수 함수).
 *
 * 한때 이 경계가 없어 `GenerateImagesFormValues`가 그대로 POST 바디였다 — 필드가 4개뿐이라
 * 분리하지 않는다는 결정이었는데(`schema.ts`의 change-password·edit-profile 선례), 바디에 타입이
 * 안 붙어 있어서 **스키마와 DTO가 이미 어긋나 있는 것조차 컴파일에 안 잡혔다**. 지금은 필드가
 * 다섯이고 그중 둘이 서버 목록에서 오는 문자열이라 위 타입이 그 경계를 명시한다. */
export function formToServer(values: GenerateImagesFormValues): GenerateImageRequestBody {
  return {
    prompt: values.prompt,
    model: values.model,
    style: values.style,
    aspectRatio: values.aspectRatio,
    count: values.count,
  };
}
