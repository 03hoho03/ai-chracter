/** 소설 삽화 스위치(가격 응답의 `novelIllustrationsEnabled`)가 켜져 있는가. 가격을 아직 못 받았거나 받지 못했거나 칸이
 * 없는 응답은 꺼짐으로 접는다. 삽화를 고치는 컨트롤은 전부 이 값 하나로만 열린다 — 이 칸을 직접 읽는 곳이 둘이 되면
 * 꺼짐·로딩을 다르게 접는 화면이 생긴다(시험이 소스를 훑어 막는다). 그림을 그리는 것은 이 값이 아니라 응답이 정한다 —
 * 서버는 꺼짐에서 삽화 목록을 비워 준다. */
export function isNovelIllustrationsOn(pricing: { novelIllustrationsEnabled?: boolean } | undefined): boolean {
  return pricing?.novelIllustrationsEnabled === true;
}
