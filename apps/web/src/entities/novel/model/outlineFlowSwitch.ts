/** 소설 구성 흐름 스위치(가격 응답의 `novelizeOutlineFlowEnabled`)가 켜져 있는가. 가격을 아직 못 받았거나 받지 못했거나 칸이
 * 없는 응답은 꺼짐으로 접는다. 편집 보드의 구성 화면과 그 입구, 구성 흐름 조회는 전부 이 값 하나로만 열린다 — 이 칸을 직접
 * 읽는 곳이 둘이 되면 꺼짐·로딩을 다르게 접는 화면이 생긴다(시험이 소스를 훑어 막는다). 서버는 꺼짐에서 구성 흐름 라우트를
 * 404 로 막으므로, 꺼짐에서 그 조회를 부르지 않는 것이 이 값의 몫이다. */
export function isNovelOutlineFlowOn(pricing: { novelizeOutlineFlowEnabled?: boolean } | undefined): boolean {
  return pricing?.novelizeOutlineFlowEnabled === true;
}
