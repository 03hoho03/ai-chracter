import type { components } from "@ai-character-chat/api-types";

import { defaultUserNameIssue } from "@/entities/persona";

import type { CharacterBuilderFormValues } from "./schema";

type CharacterDraftPayload = components["schemas"]["CharacterDraftPayload"];

/**
 * 폼값 -> `PATCH /contents/{id}/draft` payload (순수 함수).
 * 자동저장/발행/미리보기 전부 이 결과를 그대로 재사용한다 — 검증(zod parse)은 호출부 책임이다.
 *
 * situationalImages의 우선순위(order)는 서버 스키마에 별도 숫자 필드가 없다 — `PATCH .../draft`는
 * 배열 인덱스 자체를 order로 저장하므로(apps/api의 `_update_draft`), 여기서는 폼 배열 순서를 그대로
 * 유지해 전달하는 것만으로 충분하다. imageAssetId는 이 엔드포인트가 다루지 않는다
 * (`POST /assets/{id}/register-situational-image` 전용 필드) — 그래서 보내지 않는다.
 */
export function formToServer(values: CharacterBuilderFormValues): CharacterDraftPayload {
  return {
    name: values.profile.name,
    oneLiner: values.profile.oneLiner,
    thumbnailAssetId: values.profile.image?.assetId ?? null,
    intro: values.intro.firstMessage,
    exampleDialogues: values.intro.exampleDialogues,
    characterPrompt: values.prompt.characterPrompt,
    playguide: values.intro.playGuide ?? null,
    // 서버는 이 칸이 없으면 저장된 값을 그대로 둔다. 입력 중간 상태(금지 문자 등)처럼 서버가 거절할 값을 실으면 PATCH 전체가
    // 422 가 돼 다른 칸의 수정까지 저장되지 않으므로, 그동안은 빼고 보낸다(칸 아래 오류가 그 사실을 알린다). 앞뒤 공백은 서버처럼
    // 걷어 보낸다 — 미리보기는 이 값을 그대로 이름으로 쓰므로, 걷지 않으면 미리보기 화면과 서버 프롬프트의 이름이 갈린다.
    ...(defaultUserNameIssue(values.intro.defaultUserName) === null
      ? { defaultUserName: values.intro.defaultUserName.trim() }
      : {}),
    situationalImages: values.situationalImages.map((image) => ({
      id: image.id,
      triggerCondition: image.situationDescription,
    })),
    description: values.registration.description,
    genreId: values.registration.genre,
    target: values.registration.target,
    hashtags: values.registration.hashtags,
    visibility: values.registration.visibility,
    novelPermission: values.registration.novelPermission,
  };
}
