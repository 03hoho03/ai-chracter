/** 장면 헤더의 장면 — 지금 장소와 시간. 모르는 칸은 undefined 다. 미디어 북의 장면 축과는 다른 것이다. */
export type StoryScene = { place: string | undefined; time: string | undefined };

/** 지금 장면을 고르는 데 필요한 메시지 모양 — 방 메시지와 빌더 미리보기 메시지가 함께 쓴다. */
export type SceneMessage = { id: string; role: "user" | "assistant"; scene?: StoryScene };

/** 장면 이벤트가 그 응답이 캐시에 들어오기 전에 왔을 때 잠시 들고 있는 장면. */
export type PendingScene = { messageId: string; scene: StoryScene };

/**
 * 상태 줄에 보일 지금 장면. 서버가 다음 턴 판정에 넘기는 직전 장면과 같은 규칙이다.
 *
 * - AI 메시지가 없으면 시작설정의 첫 장면.
 * - 마지막 AI 메시지에 장면이 저장돼 있으면 그 장면. 앞의 사용자 메시지만 지워져 오프닝처럼 보여도 저장된 장면을 따른다.
 * - 장면이 비어 있으면 그 메시지가 오프닝(앞에 사용자 메시지가 없다)일 때만 첫 장면이고, 아니면 없음이다 — 헤더를 켜기
 *   전에 쓰인 응답 뒤에 프롤로그 장소가 다시 뜨지 않게.
 *
 * 긴 방은 최근 메시지만 받아 와서(`hasMoreMessagesBefore`) 받은 목록의 첫 AI 메시지가 오프닝인지 알 수 없다. 그때는 오프닝으로
 * 보지 않는다 — 방의 첫 메시지는 받은 목록 밖에 있다.
 *
 * 삭제·수정·재생성·직전 응답 되돌리기는 모두 캐시의 메시지 목록을 바꾸므로 이 함수를 다시 부르면 저절로 맞는다.
 */
export function selectCurrentScene(
  messages: readonly SceneMessage[],
  initialScene: StoryScene | undefined,
  { hasMoreMessagesBefore = false }: { hasMoreMessagesBefore?: boolean } = {},
): StoryScene | undefined {
  let lastIndex = messages.length - 1;
  while (lastIndex >= 0 && messages[lastIndex]?.role !== "assistant") lastIndex -= 1;
  if (lastIndex === -1) return hasMoreMessagesBefore ? undefined : initialScene;
  const saved = messages[lastIndex]?.scene;
  if (saved !== undefined) return saved;
  const isOpening = !hasMoreMessagesBefore && !messages.slice(0, lastIndex).some((message) => message.role === "user");
  return isOpening ? initialScene : undefined;
}

/** `messageId` 메시지에 장면을 붙인 새 목록. 그 메시지가 아직 목록에 없으면 undefined 다 — 부르는 쪽이 장면을 들고 있다가
 * 응답이 확정될 때 붙인다(`takePendingScene`). */
export function attachSceneToMessages<TMessage extends SceneMessage>(
  messages: readonly TMessage[],
  messageId: string,
  scene: StoryScene,
): TMessage[] | undefined {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index === -1) return undefined;
  return messages.map((message, at) => (at === index ? { ...message, scene } : message));
}

/** 확정 응답에 먼저 와 있던 장면을 붙인다. 응답이 장면을 이미 실었으면(서버가 저장한 같은 장면이다) 그대로 둔다. */
export function takePendingScene<TMessage extends SceneMessage>(
  message: TMessage,
  pending: PendingScene | undefined,
): TMessage {
  if (pending === undefined || pending.messageId !== message.id || message.scene !== undefined) return message;
  return { ...message, scene: pending.scene };
}

/** 장면 줄을 그릴 글이 있는가 — 장소·시간이 둘 다 비면 줄이 없다. */
export function hasSceneText(scene: StoryScene | undefined): scene is StoryScene {
  return scene !== undefined && (scene.place !== undefined || scene.time !== undefined);
}

/** 한 턴의 장면 변화를 스크린리더가 읽을 문장들(장소 다음 시간). 바뀌어 새 글이 생긴 칸만 읽는다 — 비게 된 칸은 화면에서
 * 사라질 뿐 알릴 내용이 없다. */
export function describeSceneChange(previous: StoryScene | undefined, next: StoryScene | undefined): string[] {
  const sentences: string[] = [];
  if (next?.place !== undefined && next.place !== previous?.place) sentences.push(`장소 바뀜: ${next.place}`);
  if (next?.time !== undefined && next.time !== previous?.time) sentences.push(`시간 바뀜: ${next.time}`);
  return sentences;
}

/** 장소·시간 글에 같은 변환(작가 매크로 펼치기)을 건다. 장면은 판정이 적은 글이라 매크로가 대개 없지만, 첫 장면은 작가가
 * 쓴 글이라 스탯 이름과 같은 경로로 펼친다. */
export function expandStoryScene(
  scene: StoryScene | undefined,
  expand: (text: string) => string,
): StoryScene | undefined {
  if (scene === undefined) return undefined;
  return {
    place: scene.place === undefined ? undefined : expand(scene.place),
    time: scene.time === undefined ? undefined : expand(scene.time),
  };
}
