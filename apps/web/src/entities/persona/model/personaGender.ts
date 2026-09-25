import type { PersonaGender } from "./persona";

/** `PersonaGender` 목록의 단일 소스 — 폼 선택지는 여기서 도출한다.
 *
 * `PersonaGender`는 `generated.ts`가 소유하므로 목록 옆으로 옮길 수 없다(`entities/content`의
 * `CONTENT_TYPES`와 같은 사정). 그래서 **목록이 타입 전체를 덮는지**를 아래 한 줄이 컴파일 타임에 강제한다 —
 * 서버가 멤버를 늘렸는데 폼에서 고를 수 없게 되는 일을 여기서 막는다. */
export const PERSONA_GENDERS = ["male", "female"] as const;

type AssertNoUncovered<T extends never> = T;
/** 멤버를 빠뜨리면 `Exclude<...>`가 `never`가 아니게 되어 이 줄에서 컴파일이 깨진다(실증: `"female"`을 빼면
 * `error TS2344: Type '"female"' does not satisfy the constraint 'never'`). 타입 레벨 단언이라 쓰이는 곳이
 * 없는 게 정상이다. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _CoversAllPersonaGenders = AssertNoUncovered<Exclude<PersonaGender, (typeof PERSONA_GENDERS)[number]>>;

/** "선택 안 함"은 서버에서 `null`이라 이 맵에 없다(표시할 줄이 없다). */
export const PERSONA_GENDER_LABEL: Record<PersonaGender, string> = {
  male: "남성",
  female: "여성",
};
