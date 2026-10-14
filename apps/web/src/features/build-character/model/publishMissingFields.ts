import type { Path } from "react-hook-form";

import type { CharacterBuilderFormValues } from "./schema";

// 서버(validate_character_publish)가 400 으로 돌려주는 필드명을 form.setError() 가 받는 폼 경로로 옮긴다. 키 집합은 그 함수가
// 내는 필드 전부다. 값은 tabs.ts(CHARACTER_TABS)의 fields 프리픽스 아래에 들어간다(profile.* 는 profile 탭, registration.* 는
// detail 탭 — 탭 id 는 "detail" 이지만 폼 경로는 스키마 키 "registration" 을 그대로 쓴다). 칸 이름은 이 경로로 칸 라벨 표
// (`CHARACTER_FIELD_LABELS`)에서 찾으므로 서버 키마다 라벨을 따로 적지 않는다.
//
// 초안 상태를 표현하느라 nullable 인 3필드(profile.image/registration.genre/registration.target)도 이제는 폼 스키마가 먼저 막지만,
// 다른 기기에서 편집된 초안처럼 서버만 아는 상태가 남아 이 경로를 지우지 않는다.
const CHARACTER_MISSING_FIELD_FORM_PATH: Readonly<Record<string, Path<CharacterBuilderFormValues> | undefined>> = {
  name: "profile.name",
  oneLiner: "profile.oneLiner",
  thumbnailAssetId: "profile.image",
  intro: "intro.firstMessage",
  characterPrompt: "prompt.characterPrompt",
  // 이미지를 올리지 않은 상황별 이미지 항목이 하나라도 있으면 서버가 이 키를 한 번 준다 — 어느 항목인지 몰라 목록 자리에 건다.
  situationalImages: "situationalImages",
  description: "registration.description",
  genreId: "registration.genre",
  target: "registration.target",
};

/** 서버 400 의 필드명을 폼 경로로 옮긴다. 빌더가 모르는 키면 `undefined`. 순수 함수. */
export function characterMissingFieldFormPath(field: string): Path<CharacterBuilderFormValues> | undefined {
  return Object.hasOwn(CHARACTER_MISSING_FIELD_FORM_PATH, field) ? CHARACTER_MISSING_FIELD_FORM_PATH[field] : undefined;
}

/** 서버가 낼 수 있는 필드명 전부 — 라벨 전수 검사가 모든 키가 칸에 걸리는지 확인하는 데 쓴다. */
export const CHARACTER_MISSING_FIELDS: readonly string[] = Object.keys(CHARACTER_MISSING_FIELD_FORM_PATH);
