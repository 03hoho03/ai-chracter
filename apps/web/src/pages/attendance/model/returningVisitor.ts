const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 86_400_000;

/** 마지막 수령일이 이만큼 이상 전이면 복귀로 본다(이틀 이상 빠졌다). */
const RETURNING_GAP_DAYS = 3;

/** 한국 시각 기준 `YYYY-MM-DD`. 서버가 출석 날짜를 한국 시각으로 세므로 견줄 오늘도 같은 시간대로 고정한다 — 브라우저
 * 시간대를 따르면 한국 밖에서 하루가 어긋난다. 이 화면만 쓰는 동안 여기 두고, 다른 화면이 쓰게 되면 공용 시간 유틸로
 * 올린다. */
export function toKstDateKey(now: Date): string {
  return new Date(now.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/** `YYYY-MM-DD` 를 달력 일수로. UTC 자정으로 바꿔 세므로 시간대·서머타임과 무관하다. */
function toDayNumber(dateKey: string): number {
  const year = Number(dateKey.slice(0, 4));
  const month = Number(dateKey.slice(5, 7));
  const day = Number(dateKey.slice(8, 10));
  return Date.UTC(year, month - 1, day) / DAY_MS;
}

/** 마지막 수령일이 오늘보다 사흘 이상 전인가(이틀 이상 빠졌는가). 하루 빠진 사람에게는 판 위 "하루 쉬어도 괜찮아요" 가
 * 이미 말하고 있어 복귀 인사가 과하다. 받은 적이 없으면 복귀가 아니고, 마지막 수령일이 오늘보다 뒤면(기기 시계가 늦은
 * 경우) 복귀로 보지 않는다 — 틀려도 인사 한 줄이 나오거나 안 나올 뿐 지급과 무관하다. */
export function isReturningAfterBreak(lastClaimedOn: string | null, todayKst: string): boolean {
  if (lastClaimedOn === null) return false;
  return toDayNumber(todayKst) - toDayNumber(lastClaimedOn) >= RETURNING_GAP_DAYS;
}
