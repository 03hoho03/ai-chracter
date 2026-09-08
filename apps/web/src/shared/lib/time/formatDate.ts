/** `YYYY.MM.DD` 표기. 공지·문의·약관 화면이 게시일/접수일을 이 모양으로 찍는다.
 *
 * `toLocaleDateString("ko-KR")`이 아니라 손으로 조립하는 이유: 로케일 포맷은 `2026. 9. 8.`처럼
 * 공백과 후행 마침표가 붙고 자릿수도 안 맞아 목록에서 열이 흔들린다. 로컬 타임존 기준이라
 * 서버가 준 UTC iso를 사용자가 보는 날짜로 옮긴다(`formatRelativeTime`과 같은 전제). */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, "0")}.${String(date.getDate()).padStart(2, "0")}`;
}
