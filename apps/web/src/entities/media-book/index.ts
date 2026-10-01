// 미디어 북 — 작성자 글 속 그림 태그(`{{img::인물/장면}}`·`{{img::<칸 id>}}`)의 문법(빌더의 이름 정규화·이름 바꾸기
// 포함)과 화면이 받는 그림 맵, 그리고 일괄 업로드의 덮어쓰기 선택지.
// 다른 entity(chat-room·preview-session)는 이 파일이 아니라 `@x/` 의 참조자 전용 공개 API 로 읽는다.
export { toMediaTagImages } from "./api/toMediaTagImages";
export {
  findMediaNameTags,
  hasMediaTag,
  normalizeMediaBookName,
  renameMediaTagName,
  splitMediaTagText,
  stripMediaTags,
  toMediaNameTag,
  type MediaBookAxis,
  type MediaTagImage,
  type MediaTagImages,
} from "./model/mediaTags";
export type { OverwriteChoice } from "./model/overwriteChoice";
