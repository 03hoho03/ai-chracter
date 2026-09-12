import type { components } from "@ai-character-chat/api-types";

import { assertNever } from "@/shared/lib/assertNever";

import type { ContentType } from "./content";

type CharacterDraftResponse = components["schemas"]["CharacterDraftResponse"];
type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];

/**
 * 초안 응답에서 서버가 부여하는 식별자만 뺀 "초안 본문". 빌더 폼(`serverToForm`)이 실제로 읽는 건
 * 이 부분뿐이라, 아직 서버에 없는 초안(US-007 지연 생성)도 같은 타입으로 다룰 수 있다.
 */
export type CharacterDraftContent = Omit<CharacterDraftResponse, "id" | "contentVersionId">;
export type StoryDraftContent = Omit<StoryDraftResponse, "id">;
export type ContentDraftContent = CharacterDraftContent | StoryDraftContent;

/**
 * `POST /contents`가 만드는 빈 초안과 같은 값을 로컬로 만든다(apps/api `create_content_draft` —
 * 텍스트는 빈 문자열, 이미지·장르·타겟은 미선택, 공개범위는 private, 스토리 템플릿은 basic).
 * 서버 왕복 없이 빌더를 바로 띄우기 위한 초기값이라, 서버 기본값이 바뀌면 여기도 함께 바뀌어야
 * 한다 — 어긋나면 첫 자동저장 직후 화면이 소리 없이 달라진다.
 *
 * `if/else`가 아니라 `switch`인 건 완전성 검사 때문이다(TS-05) — `ContentType`에 멤버가 늘면
 * `default`의 `assertNever(type)`가 컴파일 에러를 낸다. 유니언 밖 문자열이 들어오면 런타임에도
 * `assertNever`가 throw한다. 지금은 `routes/builder.$type.$draftId.tsx`의
 * `type === "story" ? "story" : "character"`가 **유일한 진입 가드**로 좁혀 넣어 도달 불가다 — 그
 * 삼항을 걷어내거나 다른 호출부를 만들면 이 가정도 같이 깨진다.
 */
export function createEmptyDraft(type: ContentType): ContentDraftContent {
  switch (type) {
    case "character":
      return {
        type: "character",
        name: "",
        oneLiner: "",
        thumbnailAssetId: null,
        thumbnailUrl: null,
        intro: "",
        exampleDialogues: [],
        characterPrompt: "",
        playguide: null,
        situationalImages: [],
        description: "",
        genreId: null,
        target: null,
        hashtags: [],
        visibility: "private",
      };
    case "story":
      return {
        type: "story",
        name: "",
        oneLiner: "",
        thumbnailAssetId: null,
        thumbnailUrl: null,
        promptTemplate: "basic",
        settingText: null,
        developmentExample: null,
        developmentExamples: [],
        userGoal: null,
        rules: null,
        customPrompt: null,
        startingSetups: [],
        keywordNotes: [],
        shortcuts: [],
        description: "",
        genreId: null,
        target: null,
        hashtags: [],
        visibility: "private",
      };
    default:
      return assertNever(type);
  }
}
