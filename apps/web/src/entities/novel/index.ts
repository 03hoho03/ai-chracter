export { novelKeys } from "./api/keys";
export { useEnsureRoomNovelMutation } from "./api/useEnsureRoomNovelMutation";
export { useNovelJobQuery, type NovelJobResponse } from "./api/useNovelJobQuery";
export { useNovelListQuery, type NovelListItem, type NovelListResponse } from "./api/useNovelListQuery";
export {
  useNovelChapterQuery,
  type NovelChapterResponse,
  type NovelRevisionResponse,
} from "./api/useNovelChapterQuery";
export {
  useNovelQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
  type NovelPendingAiEdit,
} from "./api/useNovelQuery";
export { useSetProtagonistNameMutation } from "./api/useSetProtagonistNameMutation";
export { writeNovelChapterRevision } from "./api/writeNovelChapterRevision";
export { CHAPTER_REGENERATING_MESSAGE, isChapterRegenerating } from "./model/chapterRegenerationLock";
export {
  isProtagonistNameRequiredError,
  NOVEL_ROOM_GONE_MESSAGE,
  toNovelActionError,
  toNovelJobFailureMessage,
  type NovelAction,
  type NovelActionErrorNotice,
} from "./model/novelActionError";
export {
  hasNovelErrorCode,
  isNovelizeNotAllowedError,
  toNovelLoadFailure,
  type NovelLoadFailure,
} from "./model/novelError";
export {
  hasNovelJobPollError,
  isNovelJobGone,
  isTerminalNovelJobStatus,
  type NovelJobStatus,
} from "./model/novelJobPolling";
export { NovelizeLockedState } from "./ui/NovelizeLockedState";
