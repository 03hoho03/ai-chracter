// entities/preview-session 전용 공개 API. 빌더 미리보기도 장면을 방과 같은 규칙으로 응답 메시지에 붙인다.
export {
  attachSceneToMessages,
  takePendingScene,
  type PendingScene,
  type StoryScene,
} from "../model/storyScene";
