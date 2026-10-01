// 미디어 북 — 작성자 글 속 그림 태그(`{{img::인물/장면}}`·`{{img::<칸 id>}}`)의 문법과 화면이 받는 그림 맵.
// 다른 entity(chat-room·preview-session)는 이 파일이 아니라 `@x/` 의 참조자 전용 공개 API 로 읽는다.
export { toMediaTagImages } from "./api/toMediaTagImages";
export { splitMediaTagText, stripMediaTags, type MediaTagImage, type MediaTagImages } from "./model/mediaTags";
