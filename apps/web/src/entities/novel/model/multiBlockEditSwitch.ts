/** 여러 문단 수정 스위치(가격 응답의 `novelizeMultiBlockEditEnabled`)가 켜져 있는가. 가격을 아직 못 받았거나 받지 못했거나
 * 칸이 없는 응답은 꺼짐으로 접는다. 새 요청(떨어진 문단 고르기)은 전부 이 값 하나로만 열린다 — 이 칸을 직접 읽는 곳이 둘이
 * 되면 꺼짐·로딩을 다르게 접는 화면이 생긴다(시험이 소스를 훑어 막는다). 이미 받은 수정안의 목록·적용·버리기는 이 값과
 * 상관없이 상세가 정한다 — 서버가 스위치를 끈 뒤에도 그 둘을 받는다. */
export function isNovelMultiBlockEditOn(pricing: { novelizeMultiBlockEditEnabled?: boolean } | undefined): boolean {
  return pricing?.novelizeMultiBlockEditEnabled === true;
}
