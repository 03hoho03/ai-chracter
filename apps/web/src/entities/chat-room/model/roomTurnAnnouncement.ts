import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import type { ChatRoomState, StatDef } from "./chatRoomState";
import { roomAuthorMacroNames } from "./roomAuthorMacroNames";
import { buildStatTurnAnnouncement, type StatTurnFeedback } from "./statTurnFeedback";
import { describeSceneChange, expandStoryScene, selectCurrentScene, type StoryScene } from "./storyScene";

/** 스탯 정의 가운데 플레이어에게 보이는 글(이름·단위·플레이어용 설명)의 작가 매크로를 방의 이름으로 펼친다. 상태 줄과
 * 스크린리더 턴 안내가 같은 함수를 지나야 화면과 안내의 이름이 갈리지 않는다. */
export function expandRoomStats(stats: readonly StatDef[], names: AuthorMacroNames): StatDef[] {
  const expand = (text: string) => expandAuthorMacros(text, names);
  return stats.map((stat) => ({
    ...stat,
    name: expand(stat.name),
    unit: stat.unit === undefined ? undefined : expand(stat.unit),
    playerDescription: stat.playerDescription === undefined ? undefined : expand(stat.playerDescription),
  }));
}

type SceneRoom = Pick<ChatRoomState, "contentSnapshot" | "messages" | "hasMoreMessagesBefore">;

/** 방의 지금 장면(매크로를 펴기 전). 장면 헤더를 끈 작품과 캐릭터 방은 장면이 없다. */
export function selectRoomScene(room: SceneRoom): StoryScene | undefined {
  const snapshot = room.contentSnapshot;
  if (!snapshot?.sceneHeaderEnabled) return undefined;
  return selectCurrentScene(room.messages, snapshot.initialScene, { hasMoreMessagesBefore: room.hasMoreMessagesBefore });
}

/**
 * 확정된 한 턴을 스크린리더가 한 번에 읽을 문장 — 공개 스탯 증감, 장면 변화, 익명 신호 순서다. 스탯 이름·단위와 장면 글은
 * 화면에 보이는 것과 같이 작가 매크로를 펼친 글이다.
 *
 * `previousScene` 은 턴을 보내기 직전 화면이 보이던 장면(매크로를 펴기 전)이고, 지금 장면은 `room` 의 메시지에서 고른다.
 */
export function buildRoomTurnAnnouncement(
  room: SceneRoom & Pick<ChatRoomState, "stats" | "contentType" | "personaName" | "contentName">,
  feedback: Pick<StatTurnFeedback, "deltas" | "hiddenSignal">,
  previousScene: StoryScene | undefined,
): string {
  const names = roomAuthorMacroNames(room);
  const expand = (text: string) => expandAuthorMacros(text, names);
  const stats = expandRoomStats(room.contentSnapshot?.stats ?? [], names);
  const sceneSentences = room.contentSnapshot?.sceneHeaderEnabled
    ? describeSceneChange(expandStoryScene(previousScene, expand), expandStoryScene(selectRoomScene(room), expand))
    : [];
  return buildStatTurnAnnouncement(stats, room.stats, feedback, sceneSentences);
}
