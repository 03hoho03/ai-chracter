const SNAPSHOT_TIME_FORMAT = new Intl.DateTimeFormat("ko-KR", {
  month: "long",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** 버전 목록의 저장 시각(`10월 8일 오후 11:02`). 상대 시각("3시간 전")이 아니라 날짜와 시각을 적는다 — 버전은 며칠·몇
 * 주를 두고 고르는 기준점이라, 같은 날 여럿을 저장해도 서로 갈려야 한다. 이용자가 보는 시간대(로컬)로 적는다. */
export function formatSnapshotTime(iso: string): string {
  return SNAPSHOT_TIME_FORMAT.format(new Date(iso));
}
