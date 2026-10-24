/** 메시지 키 — 서버가 방 메시지를 세우는 순서 `(created_at, id)` 를 화면에서 비교할 꼴. 시각은 초 단위 epoch 와 마이크로초로
 * 나눠 든다. */
export type MessageKey = { seconds: number; micros: number; id: string };

const DATETIME = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?$/;

/**
 * 응답의 `createdAt` 과 메시지 id 로 키를 만든다. 풀 수 없으면 키가 없다.
 *
 * 서버는 마이크로초가 0 이면 소수부를 빼고 싣는다(`…:03Z` 와 `…:03.000005Z`) — 글자로 비교하면 순서가 뒤집히고, `Date` 는 밀리초까지라
 * 같은 밀리초 안의 차이를 잃는다. 그래서 소수부를 6자리로 맞춰 따로 든다. 시간대가 없으면 UTC 로 읽는다.
 */
export function toMessageKey(createdAt: string | null | undefined, id: string): MessageKey | undefined {
  if (createdAt === null || createdAt === undefined) return undefined;
  const match = DATETIME.exec(createdAt);
  if (match === null) return undefined;
  const [, wholeSeconds, fraction = "", zone = "Z"] = match;
  const milliseconds = Date.parse(`${wholeSeconds}${zone}`);
  if (Number.isNaN(milliseconds)) return undefined;
  return { seconds: milliseconds / 1000, micros: Number(fraction.padEnd(6, "0")), id };
}

/** 서버와 같은 순서 — 시각이 먼저, 같으면 id. id 는 소문자 hex 글자 순이 서버의 uuid 순(바이트 순)과 같다. */
export function compareMessageKeys(a: MessageKey, b: MessageKey): number {
  if (a.seconds !== b.seconds) return a.seconds - b.seconds;
  if (a.micros !== b.micros) return a.micros - b.micros;
  if (a.id === b.id) return 0;
  return a.id < b.id ? -1 : 1;
}
