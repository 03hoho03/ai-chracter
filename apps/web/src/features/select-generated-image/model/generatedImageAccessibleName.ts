type GeneratedImageNameParts = {
  /** 목록에서의 순번(1부터). 한 번 생성하면 두 장이 같은 분에 생겨 시각만으로는 이름이 겹친다. */
  position: number;
  /** 만든 때를 사람이 읽는 글자로 바꾼 것(예: `10월 2일 오후 3:24`). */
  createdAtLabel: string;
  /** 채우려는 칸에 이미 들어 있는 이미지인가. */
  isCurrent?: boolean;
  /** 다른 칸에서 쓰고 있으면 그 칸들을 말하는 한 구절(예: `도희 · 진심 칸에 씀`). */
  usedLabel?: string;
};

/** 생성 이미지 고르기 버튼의 접근 이름. 이미지 내용은 글로 알 수 없으니 순번·만든 때·쓰임으로 서로를 가른다. */
export function generatedImageAccessibleName({
  position,
  createdAtLabel,
  isCurrent = false,
  usedLabel,
}: GeneratedImageNameParts): string {
  const parts = [`${position}번째 이미지`, `${createdAtLabel} 생성`];
  if (isCurrent) parts.push("지금 이 칸의 이미지");
  if (usedLabel) parts.push(usedLabel);
  return parts.join(", ");
}
