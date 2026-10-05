export { novelKeys } from "./api/keys";
export { useEnsureRoomNovelMutation } from "./api/useEnsureRoomNovelMutation";
export { useNovelJobQuery, type NovelJobResponse } from "./api/useNovelJobQuery";
export { useNovelListQuery, type NovelListItem, type NovelListResponse } from "./api/useNovelListQuery";
export { useNovelQuery, type NovelChapterSummary, type NovelDetailResponse } from "./api/useNovelQuery";
export { useSetProtagonistNameMutation } from "./api/useSetProtagonistNameMutation";
export {
  isProtagonistNameRequiredError,
  toNovelActionError,
  toNovelJobFailureMessage,
  type NovelAction,
  type NovelActionErrorNotice,
} from "./model/novelActionError";
export { isNovelizeNotAllowedError, toNovelLoadFailure, type NovelLoadFailure } from "./model/novelError";
export { hasNovelJobPollError, isTerminalNovelJobStatus, type NovelJobStatus } from "./model/novelJobPolling";
export { NovelizeLockedState } from "./ui/NovelizeLockedState";
