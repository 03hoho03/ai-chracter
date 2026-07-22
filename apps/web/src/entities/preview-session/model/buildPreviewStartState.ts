import type { components } from "@ai-character-chat/api-types";

import type { PreviewSessionState, PreviewShortcut, PreviewStartPayload, PreviewStatDef } from "../api/preview-session";

type CharacterDraftPayload = components["schemas"]["CharacterDraftPayload"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type ShortcutDraftItem = components["schemas"]["ShortcutDraftItem"];

function isCharacterPayload(payload: PreviewStartPayload): payload is CharacterDraftPayload {
  return "intro" in payload;
}

function toStatDef(item: StatDefDraftItem): PreviewStatDef {
  return {
    id: item.id,
    name: item.name,
    icon: item.icon,
    color: item.color,
    min: item.minValue,
    max: item.maxValue,
    initial: item.initialValue,
    unit: item.unit ?? undefined,
    description: item.description,
  };
}

function toShortcut(item: ShortcutDraftItem): PreviewShortcut {
  return { id: item.id, name: item.name, description: item.description, prompt: item.prompt };
}

/**
 * `POST /preview-sessions`(US-088)는 `previewSessionId`만 돌려주고 초기 상태(오프닝 메시지/스탯
 * 초기값)는 내려주지 않는다 — BE의 `_build_preview_start_state`(apps/api/src/api/chat/router.py)와
 * 동일한 계산을 FE가 그대로 재현한다. 이미 formToServer(getValues()) 결과인 payload 자체에 계산에
 * 필요한 값이 전부 들어있어(오프닝 메시지, 스탯 초기값 등) 별도 API 왕복 없이 순수 함수로 충분하다.
 */
export function buildPreviewStartState(previewSessionId: string, payload: PreviewStartPayload): PreviewSessionState {
  const now = new Date().toISOString();

  if (isCharacterPayload(payload)) {
    return {
      previewSessionId,
      contentType: "character",
      messages: [{ id: crypto.randomUUID(), role: "assistant", content: payload.intro, createdAt: now }],
      stats: {},
      statDefs: [],
      shortcuts: [],
      suggestedReplies: [],
      endingStatus: { reached: false, epilogue: null },
      turnCount: 0,
    };
  }

  // 스토리는 여러 startingSetups를 가질 수 있지만 payload엔 "미리보기할 시작설정"을 고르는 필드가
  // 없다 — BE와 동일하게 첫 번째 시작설정을 결정적으로 선택한다.
  const setup = payload.startingSetups[0];
  if (!setup) {
    return {
      previewSessionId,
      contentType: "story",
      messages: [],
      stats: {},
      statDefs: [],
      shortcuts: payload.shortcuts.map(toShortcut),
      suggestedReplies: [],
      endingStatus: { reached: false, epilogue: null },
      turnCount: 0,
    };
  }

  const openingText = setup.openingMessage || setup.prologue;
  const stats = Object.fromEntries(setup.statDefs.map((statDef) => [statDef.id, statDef.initialValue]));

  return {
    previewSessionId,
    contentType: "story",
    messages: [{ id: crypto.randomUUID(), role: "assistant", content: openingText, createdAt: now }],
    stats,
    statDefs: setup.statDefs.map(toStatDef),
    shortcuts: payload.shortcuts.map(toShortcut),
    suggestedReplies: setup.suggestedReplies,
    endingStatus: { reached: false, epilogue: null },
    turnCount: 0,
  };
}
