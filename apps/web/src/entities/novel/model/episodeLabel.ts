/** 화를 가리키는 한 줄 — `N화. 제목`, 제목이 아직 없으면(생성 전 옛 화) `N화`. 목차·읽기 화면 머리·이전/다음 화
 * 버튼이 같은 문장을 쓴다. 번호는 소설 전체 화 번호(`ordinal`)다. */
export function toEpisodeLabel({ ordinal, title }: { ordinal: number; title: string | null }): string {
  return title === null ? `${ordinal}화` : `${ordinal}화. ${title}`;
}
