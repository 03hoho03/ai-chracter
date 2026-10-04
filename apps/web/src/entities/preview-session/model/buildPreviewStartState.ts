import type { components } from "@ai-character-chat/api-types";

import { normalizeMediaTags, type MediaTagCell, type MediaTagImages } from "@/entities/media-book/@x/preview-session";

import type { PreviewStartPayload } from "../api/previewStream";
import type { PreviewSessionState, PreviewShortcut, PreviewStatDef } from "./previewSessionState";

type CharacterDraftPayload = components["schemas"]["CharacterDraftPayload"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];
type ShortcutDraftItem = components["schemas"]["ShortcutDraftItem"];
type MediaBookPayload = components["schemas"]["MediaBookPayload"];

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
 * 미리보기 첫 메시지의 id. 고정값인 이유: 세션이 생기기 전 화면은 렌더마다(입력창 글자마다) 이 함수로 다시 만들어지고,
 * 세션 시작 때도 한 번 더 만들어진다. id 가 매번 바뀌면 그 id 를 key 로 쓰는 첫 메시지(그림 포함)가 통째로 다시
 * 마운트돼 그림이 깜빡인다. 미리보기 메시지 id 는 서버로 보내지 않고(전송 페이로드는 세션 id·본문·단축어뿐) 서버가
 * 주는 응답 메시지 id 는 UUID 라, UUID 꼴이 아닌 이 값과 겹치지 않는다.
 */
export const PREVIEW_OPENING_MESSAGE_ID = "preview-opening";

/** 미디어 북 페이로드를 이름 → 칸 id 표로 편다. 인물·장면을 찾지 못한 칸은 태그가 가리킬 이름이 없어 뺀다. */
function toMediaTagCells(mediaBook: MediaBookPayload | null | undefined): MediaTagCell[] {
  if (!mediaBook) return [];
  const personNameById = new Map(mediaBook.people.map((person) => [person.id, person.name]));
  const sceneNameById = new Map(mediaBook.scenes.map((scene) => [scene.id, scene.name]));
  return mediaBook.cells.flatMap((cell) => {
    const person = personNameById.get(cell.personId);
    const scene = sceneNameById.get(cell.sceneId);
    return person === undefined || scene === undefined ? [] : [{ person, scene, cellId: cell.id }];
  });
}

/**
 * `POST /preview-sessions`는 `previewSessionId`만 돌려주고 초기 상태(오프닝 메시지/스탯
 * 초기값)는 내려주지 않는다 — BE의 `_build_preview_start_state`(apps/api/src/api/chat/router.py)와
 * 동일한 계산을 FE가 그대로 재현한다. 이미 formToServer(getValues()) 결과인 payload 자체에 계산에
 * 필요한 값이 전부 들어있어(오프닝 메시지, 스탯 초기값 등) 별도 API 왕복 없이 순수 함수로 충분하다.
 *
 * `previewSessionId`는 옵셔널이다 — 첫 전송 전에는 서버 세션이 없어
 * `PreviewSessionView`가 이 함수를 `undefined`로 호출해 로컬 플레이스홀더 상태만 그린다. placeholder
 * 문자열을 대신 넘기지 않는 이유는 그 값이 실제 전송 요청에 새어나갈 여지를 없애기 위해서다.
 *
 * 첫 메시지 속 미디어 북 태그는 실채팅에서 서버가 하는 일을 여기서 한다 — 빌더 글의 이름 형태 태그를 페이로드의
 * 미디어 북으로 칸 id 형태로 바꾸고(없는 이름은 지운다, 서버와 같은 규칙), 그 칸들의 그림을 `mediaBookImages`(빌더가
 * 가진 칸 썸네일, `{칸 id: 그림}`)에서 골라 맵을 만든다. 세션이 생기기 전 첫 그림부터 실채팅과 같은 렌더 경로를 탄다.
 */
export function buildPreviewStartState(
  previewSessionId: string | undefined,
  payload: PreviewStartPayload,
  mediaBookImages: MediaTagImages = {},
): PreviewSessionState {
  const now = new Date().toISOString();
  const authorNameSource = { defaultUserName: payload.defaultUserName ?? "", contentName: payload.name };

  if (isCharacterPayload(payload)) {
    return {
      previewSessionId,
      contentType: "character",
      authorNameSource,
      messages: [{ id: PREVIEW_OPENING_MESSAGE_ID, role: "assistant", content: payload.intro, createdAt: now }],
      openingMediaTagImages: {},
      stats: {},
      statDefs: [],
      shortcuts: [],
      suggestedReplies: [],
      endingStatus: { reached: false, epilogue: undefined },
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
      authorNameSource,
      messages: [],
      openingMediaTagImages: {},
      stats: {},
      statDefs: [],
      shortcuts: payload.shortcuts.map(toShortcut),
      suggestedReplies: [],
      endingStatus: { reached: false, epilogue: undefined },
      turnCount: 0,
    };
  }

  const opening = normalizeMediaTags(setup.openingMessage || setup.prologue, toMediaTagCells(payload.mediaBook));
  const openingMediaTagImages = Object.fromEntries(
    [...opening.cellIds].flatMap((cellId) => {
      const image = mediaBookImages[cellId];
      return image === undefined ? [] : [[cellId, image]];
    }),
  );
  const stats = Object.fromEntries(setup.statDefs.map((statDef) => [statDef.id, statDef.initialValue]));

  return {
    previewSessionId,
    contentType: "story",
    authorNameSource,
    messages: [{ id: PREVIEW_OPENING_MESSAGE_ID, role: "assistant", content: opening.text, createdAt: now }],
    openingMediaTagImages,
    stats,
    statDefs: setup.statDefs.map(toStatDef),
    shortcuts: payload.shortcuts.map(toShortcut),
    suggestedReplies: setup.suggestedReplies,
    endingStatus: { reached: false, epilogue: undefined },
    turnCount: 0,
  };
}
