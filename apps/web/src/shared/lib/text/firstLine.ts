/** 여러 줄 글의 첫 줄(앞뒤 공백 제거). 접기 머리 줄 요약은 한 줄로 잘리므로 줄바꿈 뒤는 버린다. */
export function firstLine(text: string): string {
  return text.split("\n", 1)[0]?.trim() ?? "";
}
