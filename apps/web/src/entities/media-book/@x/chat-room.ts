// entities/chat-room 전용 공개 API. 채팅 렌더러가 첫 메시지·에필로그 속 칸 id 태그를 그림으로 바꾸고(태그 판정·
// 맵 밖 칸 지우기), 방 응답·스트림의 그림 맵을 앱 모양으로 받는 데 쓴다.
export { mediaTagImagesSchema } from "../api/mediaTagImagesSchema";
export { toMediaTagImages } from "../api/toMediaTagImages";
export { dropUnresolvedMediaTags, findMediaIdTags, type MediaTagImages } from "../model/mediaTags";
