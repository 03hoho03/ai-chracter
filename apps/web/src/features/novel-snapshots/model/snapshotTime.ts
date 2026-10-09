/** 버전 목록의 저장 시각(`10월 8일 오후 11:02`). 상대 시각("3시간 전")이 아니라 날짜와 시각을 적는다 — 버전은 며칠·몇
 * 주를 두고 고르는 기준점이라, 같은 날 여럿을 저장해도 서로 갈려야 한다. 이용자가 보는 시간대(로컬)로 적는다.
 *
 * `Intl.DateTimeFormat("ko-KR")` 이 아니라 손으로 조립하는 이유: 오전·오후 표기가 런타임의 ICU 데이터에 따라
 * 갈린다 — 같은 코드가 이 저장소 CI 의 Node 20 에서는 `PM` 으로 나왔다. 실행 환경과 무관하게 같은 글자를 쓴다. */
export function formatSnapshotTime(iso: string): string {
  const date = new Date(iso);
  const hours = date.getHours();
  const period = hours < 12 ? "오전" : "오후";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}월 ${date.getDate()}일 ${period} ${hour12}:${minutes}`;
}
