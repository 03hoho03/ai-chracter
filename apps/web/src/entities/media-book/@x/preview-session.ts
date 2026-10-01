// entities/preview-session 전용 공개 API. 빌더 미리보기 첫 메시지를 서버와 같은 규칙으로 정규화하고(이름 → 칸 id),
// 미리보기 스트림의 그림 맵을 받는 데 쓴다. `NORMALIZE_CASES` 등은 서버 테스트 표를 옮긴 입력 표로, 미리보기
// 정규화 테스트가 같은 표를 쓰게 하려고 연다(앱 코드는 읽지 않는다).
export { mediaTagImagesSchema } from "../api/mediaTagImagesSchema";
export { CELLS, MINA_CLASSROOM, MINA_ROOFTOP, NORMALIZE_CASES } from "../model/mediaTagCases";
export { normalizeMediaTags, type MediaTagCell, type MediaTagImages } from "../model/mediaTags";
