import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

import type { NovelJobResponse } from "../api/useNovelJobQuery";
import { toNovelizeForbiddenCopy } from "./novelError";

/** 오류를 받은 요청이 무엇이었나. 같은 코드라도 요청에 따라 문장이 갈리는 자리가 있다 — 시간당 상한과 하루
 * 상한이 같은 429 로 오고, 이용 제한·일반 실패도 무엇을 못 했는지가 달라서다. */
export type NovelAction =
  | "proposal"
  | "generate"
  | "regenerate"
  | "aiEdit"
  | "applyAiEdit"
  | "dismissAiEdit"
  | "applyPatch"
  | "dismissPatch"
  | "recheckBundle"
  | "edit"
  | "restore"
  | "notes"
  | "deleteChapter"
  | "deleteNovel"
  | "protagonistName"
  | "title"
  | "synopsis"
  | "cover"
  | "chain"
  | "chapterTitle"
  | "authorNote"
  | "character"
  | "mergeCharacter"
  | "saveSnapshot"
  | "restoreSnapshot"
  | "deleteSnapshot"
  | "attachIllustration"
  | "moveIllustration"
  | "replaceIllustration"
  | "detachIllustration"
  | "saveSourceSelection"
  | "approveSourceSelection"
  | "outline"
  | "saveOutline"
  | "approveOutline"
  | "episodeOutline"
  | "saveEpisodeOutline"
  | "approveEpisodeOutline"
  | "outlineChapter"
  | "outlineRegenerate";

export type NovelActionErrorNotice = {
  message: string;
  /** 상세를 다시 받아야 화면이 맞아지는 실패인가 — 단가·진행 중 작업·장 목록·대화방 유무가 서버에서 바뀌었다는
   * 뜻이다. 진행 중 작업 409 는 다시 받은 상세의 `activeJob` 으로 폴링을 이어 간다. */
  shouldRefetchNovel: boolean;
};

const ACTION_OBJECT: Record<NovelAction, string> = {
  proposal: "다음 화를 준비하지",
  generate: "화를 만들지",
  regenerate: "화를 다시 만들지",
  aiEdit: "AI로 고치지",
  applyAiEdit: "수정안을 적용하지",
  dismissAiEdit: "수정안을 버리지",
  applyPatch: "수정안을 적용하지",
  dismissPatch: "수정안을 버리지",
  recheckBundle: "묶음을 다시 검사하지",
  edit: "고친 내용을 저장하지",
  restore: "이 판으로 되돌리지",
  notes: "설정 노트를 저장하지",
  deleteChapter: "화를 지우지",
  deleteNovel: "소설을 지우지",
  protagonistName: "주인공 이름을 저장하지",
  title: "제목을 저장하지",
  synopsis: "소개를 저장하지",
  cover: "표지를 바꾸지",
  chain: "남은 대화를 소설로 만들지",
  chapterTitle: "화 제목을 저장하지",
  authorNote: "작가의 말을 저장하지",
  character: "인물 카드를 저장하지",
  mergeCharacter: "인물 카드를 합치지",
  saveSnapshot: "버전을 저장하지",
  restoreSnapshot: "이 버전으로 되돌리지",
  deleteSnapshot: "버전을 지우지",
  attachIllustration: "삽화를 붙이지",
  moveIllustration: "삽화를 옮기지",
  replaceIllustration: "삽화를 바꾸지",
  detachIllustration: "삽화를 떼지",
  saveSourceSelection: "고른 구간을 저장하지",
  approveSourceSelection: "고른 구간을 승인하지",
  outline: "전체 구성안을 만들지",
  saveOutline: "구성안을 저장하지",
  approveOutline: "구성안을 승인하지",
  episodeOutline: "장면 구성안을 만들지",
  saveEpisodeOutline: "장면 구성안을 저장하지",
  approveEpisodeOutline: "장면 구성안을 승인하지",
  outlineChapter: "원고를 쓰지",
  outlineRegenerate: "화를 다시 만들지",
};

/** 원래 대화방이 지워져 화를 만들 수도 다시 만들 수도 없을 때의 문장. 만들기 버튼 아래 사유 문장과 두 요청의 409 가
 * 같은 문장을 쓴다 — 409 문구는 요청 종류를 보지 않아서, 만들기만 말하면 다시 만들기에서 받았을 때 틀린 말이 된다. */
export const NOVEL_ROOM_GONE_MESSAGE = "원래 대화방이 지워져 새 화를 만들거나 다시 만들 수 없어요.";

const SOURCE_MISMATCH_MESSAGE = "고른 구간을 대화와 맞추지 못했어요. 대화를 새로 불러왔어요. 구간을 다시 골라주세요.";

/** 코드 → 문구. 기다려도 풀리지 않는 거부는 "다시 시도"를 말하지 않고, 이용자가 할 수 있는 다음 일을 말한다. */
const MESSAGE_BY_CODE: Record<string, NovelActionErrorNotice> = {
  // 행동 중에 허용이 회수된 경우다. 상세를 다시 받으면 그 조회도 403 이라 화면이 잠김 화면으로 넘어간다.
  NOVELIZE_NOT_ALLOWED: { message: "소설로 보기를 지금 이 계정에서 쓸 수 없어요.", shouldRefetchNovel: true },
  // 고른 상위 모델을 쓸 허용이 없다(기능이 꺼졌거나 허용을 거뒀다). 상세를 다시 받으면 고를 수 있는 모델 목록이 줄어
  // 다음 확인 화면이 맞아진다.
  NOVEL_MODEL_NOT_ALLOWED: {
    message: "고른 모델을 지금 이 계정에서 쓸 수 없어요. 다른 모델을 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_NOT_FOUND: { message: "소설이 지워졌어요. 내 소설에서 다시 확인해주세요.", shouldRefetchNovel: true },
  NOVEL_FORBIDDEN: { message: "이 계정의 소설이 아니에요.", shouldRefetchNovel: true },
  NOVEL_CURSOR_INVALID: { message: "목록을 처음부터 다시 불러와주세요.", shouldRefetchNovel: false },
  NOVEL_JOB_NOT_FOUND: { message: "작업을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_CHAPTER_NOT_FOUND: { message: "이 화가 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_BATCH_NOT_FOUND: { message: "함께 만든 화들이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_NOT_FOUND: { message: "이 판을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_ROOM_GONE: { message: NOVEL_ROOM_GONE_MESSAGE, shouldRefetchNovel: true },
  NOVEL_PROTAGONIST_NAME_REQUIRED: { message: "주인공 이름을 먼저 정해주세요.", shouldRefetchNovel: true },
  NOVEL_NOTHING_NEW: {
    message: "화로 묶을 새 대화가 없어요. 대화를 더 이어 간 뒤 만들어주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_END_INVALID: {
    message: "고른 턴으로는 화를 끝낼 수 없어요. 다음 화 만들기를 다시 눌러 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_NOT_LAST: { message: "마지막 화만 지울 수 있어요.", shouldRefetchNovel: true },
  NOVEL_BATCH_NOT_LAST: { message: "마지막에 함께 만든 화들만 지울 수 있어요.", shouldRefetchNovel: true },
  // 지우는 동안 노벨에서 새로 소장한 회원이 계속 생겼다(한 번은 저절로 다시 보낸 뒤다). 환급 고지의 수가 바뀌었으니
  // 상세를 다시 받는다.
  NOVEL_DELETE_CONFLICT: {
    message: "그사이 노벨에서 소장한 회원이 생겼어요. 바뀐 환급 안내를 확인하고 다시 지워 주세요.",
    shouldRefetchNovel: true,
  },
  // 마지막 묶음 화를 노벨에서 소장한 회원이 있어 서버가 아무것도 지우지 않았다(삭제 확인 값이 낡았던 경우). 다시 받은
  // 상세의 판매 표시로 지우기 버튼이 잠긴다. 소설 전체를 지우면 숨겨 둘 수 있다는 다음 길을 말한다.
  NOVEL_BATCH_SOLD: {
    message: "노벨에서 소장한 회원이 있는 화라 지울 수 없어요. 소설 전체를 지우면 숨겨 둘 수 있어요.",
    shouldRefetchNovel: true,
  },
  NOVEL_PARAGRAPH_RANGE_INVALID: { message: "고른 문단이 바뀌었어요. 다시 골라주세요.", shouldRefetchNovel: true },
  NOVEL_JOB_NOT_APPLICABLE: { message: "이 수정안은 더 이상 적용할 수 없어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_CONFLICT: {
    message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  // 직접 수정이 문단마다 실은 블록 id 가 본문 문단·기준 판과 맞지 않는다. 화면 계산이 서버와 어긋났을 때만 닿으므로 id 없이
  // 저절로 다시 보내지 않는다(어긋남을 가린다). 입력칸은 그대로 두고 상세를 다시 받는다.
  NOVEL_BLOCK_IDS_INVALID: {
    message: "문단을 맞추지 못해 저장하지 못했어요. 쓴 글을 복사해 두고 취소한 뒤 최신 글에서 다시 골라 주세요.",
    shouldRefetchNovel: true,
  },
  // 한 화에 둘 수 있는 삽화 수를 채웠다(위치 확인이 필요한 그림도 센다). 다른 그림을 떼면 붙일 수 있다.
  NOVEL_ILLUSTRATION_LIMIT_EXCEEDED: {
    message: "한 화에는 삽화를 10장까지 넣을 수 있어요. 다른 삽화를 뗀 뒤 다시 붙여 주세요.",
    shouldRefetchNovel: true,
  },
  // 삽화를 놓을 문단이 지금 판에 없다. 판을 확인한 뒤라 화면이 낡은 문단을 보낸 경우뿐이다 — 다시 받아 고르게 한다.
  NOVEL_ILLUSTRATION_ANCHOR_INVALID: {
    message: "고른 문단이 바뀌었어요. 최신 내용을 불러왔어요. 다시 골라 주세요.",
    shouldRefetchNovel: true,
  },
  // 고른 그림을 그 출처로 쓸 수 없다(남의 것·준비 안 됨·삽화 용도가 아닌 업로드·그사이 원작 이용 제한 등 — 서버가 가르지
  // 않는다). 판은 그대로라 다시 받을 것이 없고, 다른 그림을 고르면 된다.
  NOVEL_ILLUSTRATION_ASSET_INVALID: {
    message: "이 그림은 삽화로 쓸 수 없어요. 다른 그림을 골라 주세요.",
    shouldRefetchNovel: false,
  },
  // 옮기거나 바꾸거나 뗄 삽화가 지금 판에 없다(배치 id 는 판마다 새로 매겨진다).
  NOVEL_ILLUSTRATION_NOT_FOUND: {
    message: "이 삽화가 그사이 바뀌었어요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  // 삽화 스위치가 꺼졌다. 호출부가 가격 응답도 다시 받아 삽화 컨트롤을 거둔다.
  NOVEL_ILLUSTRATIONS_DISABLED: {
    message: "지금은 삽화를 넣거나 고칠 수 없어요.",
    shouldRefetchNovel: true,
  },
  NOVEL_SOURCE_CHANGED: {
    message: "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.",
    shouldRefetchNovel: false,
  },
  // 다시 만들기 목록이 낡았다(그사이 허용 모델·묶음이 바뀌었다) — 상세를 다시 받으면 비활성 항목과 이유가 맞아진다.
  // 이유별 문장은 아래에서 `reason` 을 보고 고른다.
  NOVEL_MODEL_INELIGIBLE: {
    message: "고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_COVER_INVALID: { message: "고른 이미지는 표지로 쓸 수 없어요. 다른 이미지를 골라주세요.", shouldRefetchNovel: false },
  NOVEL_CHARACTER_NOT_FOUND: { message: "이 인물이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_CHARACTER_NAME_TAKEN: { message: "같은 이름의 인물이 이미 있어요. 다른 이름을 써주세요.", shouldRefetchNovel: false },
  NOVEL_CHARACTER_MERGE_SELF: { message: "같은 인물끼리는 합칠 수 없어요.", shouldRefetchNovel: false },
  NOVEL_SNAPSHOT_NOT_FOUND: { message: "이 버전이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_SNAPSHOT_LIMIT: {
    message: "이름 붙인 버전이 가득 찼어요. 쓰지 않는 버전을 지운 뒤 다시 저장해주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_BOARD_LAYOUT_TOO_LARGE: {
    message: "편집 보드 배치가 너무 커서 저장하지 못했어요. 카드 몇 개를 정리한 뒤 다시 해주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_JOB_IN_PROGRESS: {
    message: "이미 진행 중인 작업이 있어요. 끝나면 다시 해주세요.",
    shouldRefetchNovel: true,
  },
  // 여러 문단 수정 스위치가 꺼졌다. 호출부가 가격 응답도 다시 받아 여러 문단 고르기를 거둔다(받은 수정안의 적용·버리기는 남는다).
  NOVEL_MULTI_BLOCK_EDIT_DISABLED: {
    message: "지금은 여러 문단을 함께 고칠 수 없어요.",
    shouldRefetchNovel: true,
  },
  // 고른 문단들이 두 장면에 걸쳤다. 화면이 미리 막으므로 그사이 장면 경계가 바뀐 경우뿐이다 — 다시 받아 고르게 한다.
  NOVEL_BLOCKS_NOT_IN_ONE_SCENE: {
    message: "같은 장면 안의 문단만 함께 고칠 수 있어요. 최신 내용을 불러왔어요. 다시 골라 주세요.",
    shouldRefetchNovel: true,
  },
  // 모델에 보낼 글(그 장면 전체와 설정)이 상한을 넘었다. 문단을 덜 골라도 장면은 그대로라 같은 결과다.
  NOVEL_EDIT_INPUT_TOO_LONG: {
    message: "이 장면이 길어 AI로 고칠 수 없어요. 직접 고쳐 주세요.",
    shouldRefetchNovel: false,
  },
  // 단위의 블록 중 하나라도 그사이 바뀌었다(서버는 아무것도 쓰지 않았다). 다시 받으면 그 수정안이 쓸 수 없음으로 보인다.
  NOVEL_PATCH_STALE: {
    message: "그사이 글이 바뀐 문단이 있어 적용하지 않았어요.",
    shouldRefetchNovel: true,
  },
  // 묶음에 고친 원소가 없다 — 화면이 미리 막으므로 그사이 다른 곳에서 그 문단을 되돌린 경우다. 다시 받으면 함께 적용이 열린다.
  NOVEL_RECHECK_NOT_NEEDED: {
    message: "고친 문단이 없어 묶음째 적용하면 돼요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  // 판정 모델을 부르지 못했다. 서버는 묶음을 바꾸지 않았다.
  NOVEL_RECHECK_UNAVAILABLE: {
    message: "지금 다시 검사하지 못했어요. 묶음은 그대로예요. 잠시 후 다시 해 주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_PATCH_NOT_FOUND: {
    message: "이 수정안을 찾을 수 없어요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  // 구성 흐름 스위치가 꺼졌다. 호출부가 가격 응답도 다시 받아 구성 화면을 거둔다.
  NOVEL_OUTLINE_FLOW_DISABLED: { message: "지금은 구성 흐름을 쓸 수 없어요.", shouldRefetchNovel: false },
  // 다른 탭이 먼저 저장·승인했다. 호출부가 고친 것을 버리고 선택을 다시 받는다.
  NOVEL_SOURCE_SELECTION_CONFLICT: {
    message: "다른 곳에서 고른 구간이 바뀌었어요. 새로 불러왔어요.",
    shouldRefetchNovel: false,
  },
  // 저장 뒤 고른 대화가 고쳐지거나 지워졌다. 초안은 서버에 남아 있고, 다시 받으면 바뀐 구간(서버가 구간마다 알린다)의 턴에 표시가 붙는다.
  NOVEL_SOURCE_SELECTION_SOURCE_CHANGED: {
    message: "고른 대화 중 바뀐 곳이 있어요. 표시한 구간을 확인한 뒤 다시 승인해주세요.",
    shouldRefetchNovel: false,
  },
  // 아래 셋은 화면이 막는 값이 서버에 닿은 경우다(그사이 대화가 지워졌거나 화면 계산이 어긋났다). 무엇이 어긋났는지는 이용자가
  // 할 일을 바꾸지 않아 한 문장이다.
  NOVEL_SOURCE_MESSAGE_NOT_FOUND: { message: SOURCE_MISMATCH_MESSAGE, shouldRefetchNovel: false },
  NOVEL_SOURCE_SECTION_INVALID: { message: SOURCE_MISMATCH_MESSAGE, shouldRefetchNovel: false },
  NOVEL_SOURCE_SECTION_OUT_OF_RANGE: { message: SOURCE_MISMATCH_MESSAGE, shouldRefetchNovel: false },
  // 그사이 그 구간으로 화가 생겼다. 다시 받은 잠금이 그 턴을 담기에서 뺀다.
  NOVEL_SOURCE_SECTION_LOCKED: {
    message: "이미 화로 쓴 대화는 다시 담을 수 없어요. 새로 불러왔어요.",
    shouldRefetchNovel: false,
  },
  NOVEL_SOURCE_SELECTION_EMPTY: {
    message: "담을 대화를 하나 이상 골라주세요. AI 답이 든 턴이어야 해요.",
    shouldRefetchNovel: false,
  },
  // 구성안을 만들려면 담을 대화를 승인해 둬야 한다. 화면이 미리 막으므로 다른 탭에서 승인 전 판을 새로 만든 경우다.
  NOVEL_SOURCE_SELECTION_REQUIRED: { message: "먼저 담을 대화를 골라 승인해주세요.", shouldRefetchNovel: false },
  // 구성안이 근거로 쓴 구간이 지금 승인한 담을 대화에서 빠졌다. 호출부가 구성안을 다시 받아 낡음 표시를 그린다.
  NOVEL_OUTLINE_STALE: {
    message: "구간을 바꿔 이 구성안은 낡았어요. 새로 만들거나 구간을 되돌려주세요.",
    shouldRefetchNovel: false,
  },
  // 다른 탭이 먼저 저장·승인했다(또는 구성안 작업이 새 판을 냈다). 호출부가 고친 것을 버리고 구성안을 다시 받는다.
  NOVEL_OUTLINE_CONFLICT: { message: "다른 곳에서 구성안을 고쳤어요. 새로 불러왔어요.", shouldRefetchNovel: false },
  // 이 계정이 고를 수 있는 어느 원고 모델의 턴 상한보다도 긴 화가 있어 승인을 막았다. 구성안 화면은 화 번호를 짚는 문구로 바꿔 말한다.
  NOVEL_OUTLINE_EPISODE_TOO_LONG: {
    message: "어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요. 나눈 뒤 승인해주세요.",
    shouldRefetchNovel: false,
  },
  // 아래는 화별 장면 구성안·원고의 거절이다. 화면이 미리 막으므로 대개 그사이 다른 탭이 구성안·장면 구성안·원고를 바꾼 경우라, 호출부가
  // 구성안과 그 화를 다시 받는다.
  NOVEL_OUTLINE_REQUIRED: { message: "전체 구성안을 먼저 승인해주세요.", shouldRefetchNovel: false },
  NOVEL_OUTLINE_EPISODE_NOT_FOUND: {
    message: "이 화가 지금 승인한 구성안에 없어요. 구성안을 새로 불러왔어요.",
    shouldRefetchNovel: false,
  },
  NOVEL_OUTLINE_EPISODE_WRITTEN: { message: "이 화는 이미 원고가 있어요. 구성안을 새로 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER: {
    message: "앞 화부터 차례로 써야 해요. 앞 화 원고를 먼저 써주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_EPISODE_OUTLINE_REQUIRED: { message: "장면 구성안을 승인한 뒤 원고를 쓸 수 있어요.", shouldRefetchNovel: false },
  // 전체 구성안을 고쳐 이 화의 근거가 바뀌었다. 장면 구성안은 고치거나 승인할 수 없고 다시 만들어야 한다.
  NOVEL_EPISODE_OUTLINE_STALE: {
    message: "전체 구성안에서 이 화의 근거가 바뀌어 장면 구성안이 낡았어요. 장면 구성안을 다시 만들어주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_EPISODE_OUTLINE_CONFLICT: { message: "다른 곳에서 장면 구성안을 고쳤어요. 새로 불러왔어요.", shouldRefetchNovel: false },
  // 화 종류와 다른 다시 만들기 라우트에 닿았다. 화면이 화 종류로 버튼을 가르므로 상세가 낡은 경우뿐이다 — 다시 받으면 맞는 버튼이 된다.
  NOVEL_CHAPTER_OUTLINE_FLOW: {
    message: "구성안으로 쓴 화는 구성안으로 다시 만들어요. 소설을 다시 불러왔어요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_NOT_OUTLINE_FLOW: {
    message: "이 화는 대화로 바로 만든 화라 그 방식으로 다시 만들어요. 소설을 다시 불러왔어요.",
    shouldRefetchNovel: true,
  },
  CONTENT_RESTRICTED: {
    message: "이용이 제한된 작품이라 새로 쓰는 작업을 할 수 없어요. 지금까지 만든 화는 그대로 볼 수 있어요.",
    shouldRefetchNovel: false,
  },
};

/** 구성안 저장의 편집 검증 거절(`NOVEL_OUTLINE_INVALID`) 이유별 문장. 화면이 미리 막는 규칙들이라, 닿았다면 그사이 대화·구성안이
 * 바뀌었거나 화면 계산이 서버와 어긋난 것이다 — 다시 받는 경우는 그렇다고 말한다. */
const OUTLINE_INVALID_MESSAGE: Record<string, string> = {
  too_many_episodes: "화가 너무 많아요. 화를 합치거나 지운 뒤 저장해주세요.",
  unknown_key: "다른 곳에서 구성안이 바뀌어 저장하지 못했어요. 새로 불러왔어요.",
  basis_not_found: "근거 대화 중 지워진 메시지가 있어 저장하지 못했어요. 대화와 구성안을 새로 불러왔어요.",
  basis_outside_include: "담은 대화 밖의 턴은 화에 넣을 수 없어요. 구성안을 새로 불러왔어요.",
  basis_overlap: "두 화가 같은 턴을 나눠 가질 수 없어요.",
  basis_splits_turn: "대화 한 턴을 두 화로 가를 수 없어요.",
};

/** 장면 구성안 저장의 편집 검증 거절(`NOVEL_EPISODE_OUTLINE_INVALID`) 이유별 문장. 이 화면은 장면 근거를 고치지 않으므로 어느 이유든
 * 서버 판이나 대화가 그사이 바뀐 것이다 — 호출부가 고친 것을 버리고 다시 받는다. */
const EPISODE_OUTLINE_INVALID_MESSAGE: Record<string, string> = {
  unknown_id: "다른 곳에서 장면 구성안이 바뀌어 저장하지 못했어요. 새로 불러왔어요.",
  basis_not_found: "근거 대화 중 지워진 메시지가 있어 저장하지 못했어요. 대화와 장면 구성안을 새로 불러왔어요.",
  basis_outside_episode: "이 화의 근거 밖 대화는 장면에 넣을 수 없어요. 장면 구성안을 새로 불러왔어요.",
  basis_overlap: "두 장면이 같은 턴을 나눠 가질 수 없어요. 장면 구성안을 새로 불러왔어요.",
  basis_splits_turn: "대화 한 턴을 두 장면으로 가를 수 없어요. 장면 구성안을 새로 불러왔어요.",
};

function detailCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  const { code } = detail;
  return typeof code === "string" ? code : undefined;
}

function reasonOf(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("reason" in detail)) return undefined;
  const { reason } = detail;
  return typeof reason === "string" ? reason : undefined;
}

function currentCostOf(detail: unknown): number | undefined {
  if (!detail || typeof detail !== "object" || !("currentCost" in detail)) return undefined;
  const { currentCost } = detail;
  return typeof currentCost === "number" ? currentCost : undefined;
}

function numberOf(detail: unknown, key: string): number | undefined {
  if (!detail || typeof detail !== "object") return undefined;
  const value: unknown = Object.entries(detail).find(([name]) => name === key)?.[1];
  return typeof value === "number" ? value : undefined;
}

/** 적용이 낡음 409 로 거절됐을 때 서버가 짚은 수정안 id. 다른 실패면 빈 목록이다. */
export function toStalePatchIds(error: unknown): string[] {
  if (!isApiError(error) || detailCode(error.detail) !== "NOVEL_PATCH_STALE") return [];
  const { detail } = error;
  if (!detail || typeof detail !== "object" || !("stalePatchIds" in detail)) return [];
  const { stalePatchIds } = detail;
  return Array.isArray(stalePatchIds) ? stalePatchIds.filter((id): id is string => typeof id === "string") : [];
}

function fallback(action: NovelAction): NovelActionErrorNotice {
  return { message: `${ACTION_OBJECT[action]} 못했어요. 잠시 후 다시 시도해주세요.`, shouldRefetchNovel: false };
}

/** 소설 요청 실패 → 화면에 남길 문구. `null` 은 이 화면이 말하지 않는 실패다 — 재동의 403 은 전역 재동의
 * 모달이 맡는다.
 *
 * 429 는 코드보다 먼저 본다. 제안의 시간당 상한과 장 생성·재생성의 하루 상한이 같은 `USER_LIMIT`·같은
 * `novelize` 창으로 오고 요청으로만 갈리기 때문이다. 하루 상한은 서버가 한국 날짜로 세므로 자정을 말해도 참이다.
 * 모르는 코드(서버가 새 코드를 더했는데 여기 아직 없을 때)는 요청별 일반 문구로 접는다. */
export function toNovelActionError(
  error: unknown,
  action: NovelAction,
  options: { isPolicyV2Enabled?: boolean } = {},
): NovelActionErrorNotice | null {
  const rateLimit = getRateLimitDetail(error);
  if (rateLimit?.window === "novelize") {
    if (rateLimit.code === "CLOVER_REQUIRED") {
      return { message: "클로버가 부족해요. 클로버를 채운 뒤 다시 해주세요.", shouldRefetchNovel: false };
    }
    if (rateLimit.code === "USER_LIMIT" && action === "recheckBundle") {
      // 다시 검사는 무료라 시간당 상한만 있다 — 서버가 준 남은 시간을 분으로 올려 말한다.
      const minutes = Math.max(1, Math.ceil(rateLimit.retryAfterSeconds / 60));
      return {
        message: `다시 검사를 너무 자주 했어요. ${minutes.toLocaleString()}분 뒤에 다시 검사할 수 있어요. 묶음은 그대로예요.`,
        shouldRefetchNovel: false,
      };
    }
    if (rateLimit.code === "USER_LIMIT") {
      return action === "proposal"
        ? { message: "다음 화 준비를 너무 자주 요청했어요. 잠시 후 다시 시도해주세요.", shouldRefetchNovel: false }
        : {
            message: "같은 화를 오늘 만들 수 있는 횟수를 다 썼어요. 자정이 지나면 다시 만들 수 있어요.",
            shouldRefetchNovel: false,
          };
    }
  }

  if (!isApiError(error)) return fallback(action);
  const code = detailCode(error.detail);
  if (code === undefined) return fallback(action);
  // 재동의 403 은 전역 재동의 모달이 맡는다(같은 엔티티 밖 판정 함수를 끌어오지 않으려고 코드로 직접 본다).
  if (error.status === 403 && code === "LEGAL_RECONSENT_REQUIRED") return null;

  // 아직 첫 화가 없는 남의 작품 소설에서 원작자가 소설 만들기를 허용하지 않을 때(스위치가 켜져 있으면 원작자가 탈퇴했을
  // 때도) 온다. 첫 화를 만든 소설은 이 거절을 받지 않으므로 "새 화"로 다시 만들기·AI 수정까지 아우른다. 문장은 스위치에
  // 따라 다르다(`toNovelizeForbiddenCopy`) — 호출부가 가격 응답의 스위치를 넘기지 않으면 꺼짐 문장이다.
  if (code === "CONTENT_NOVELIZE_FORBIDDEN") {
    const copy = toNovelizeForbiddenCopy({ novelPublicPolicyV2Enabled: options.isPolicyV2Enabled });
    return { message: copy.chapter, shouldRefetchNovel: false };
  }
  if (code === "NOVELIZE_PRICE_CHANGED") {
    const currentCost = currentCostOf(error.detail);
    return {
      message:
        currentCost === undefined
          ? "클로버 가격이 바뀌었어요. 바뀐 가격을 확인하고 다시 해주세요."
          : `클로버 가격이 ${currentCost.toLocaleString()}개로 바뀌었어요. 바뀐 가격을 확인하고 다시 해주세요.`,
      shouldRefetchNovel: true,
    };
  }
  if (code === "NOVEL_MODEL_INELIGIBLE") {
    const reason = reasonOf(error.detail);
    if (reason === "too_many_turns" && action === "outlineChapter") {
      return {
        message: "장면이 담은 대화가 길어 고른 모델로는 원고를 쓸 수 없어요. 다른 모델을 골라주세요.",
        shouldRefetchNovel: true,
      };
    }
    if (reason === "too_many_turns" && action === "outlineRegenerate") {
      return { message: "대화가 길어 고른 모델로는 이 화를 다시 만들 수 없어요. 다른 모델을 골라주세요.", shouldRefetchNovel: true };
    }
    if (reason === "too_many_turns") {
      return { message: "대화가 길어 고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.", shouldRefetchNovel: true };
    }
    if (reason === "too_many_episodes") {
      return { message: "화가 많아 고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.", shouldRefetchNovel: true };
    }
  }
  if (code === "NOVEL_TOO_MANY_BLOCKS") {
    const maxBlocks = numberOf(error.detail, "maxBlocks");
    return {
      message:
        maxBlocks === undefined
          ? "한 번에 고칠 수 있는 문단 수를 넘었어요. 문단을 줄여 다시 골라 주세요."
          : `한 번에 ${maxBlocks.toLocaleString()}개 문단까지 고칠 수 있어요.`,
      shouldRefetchNovel: true,
    };
  }
  if (code === "NOVEL_CHAPTER_TOO_LONG") {
    const maxChars = numberOf(error.detail, "maxChars");
    return {
      message:
        maxChars === undefined
          ? "적용하면 화가 너무 길어져요. 다른 문단을 줄인 뒤 적용해 주세요."
          : `적용하면 화가 ${maxChars.toLocaleString()}자를 넘어요. 다른 문단을 줄인 뒤 적용해 주세요.`,
      shouldRefetchNovel: false,
    };
  }
  // 표의 문구는 직접 수정 저장의 말이다("쓴 글을 복사해 두고…"). AI 수정 요청에서는 고른 문단이 지금 판과 어긋난 것이다.
  // 표의 문구는 적용의 말이다. 버리기에서 받으면 그 수정안은 다른 곳에서 이미 적용했거나 버린 것이다.
  // 다시 검사에서는 묶음이 그사이 바뀌었거나(다른 곳에서 적용·버림) 물을 거리가 없어졌다는 뜻이고, 스위치가 꺼졌으면 남은 길은
  // 함께 버리기다.
  if (code === "NOVEL_JOB_NOT_APPLICABLE" && action === "recheckBundle") {
    return { message: "이 묶음은 그사이 바뀌어 다시 검사하지 못했어요. 최신 내용을 불러왔어요.", shouldRefetchNovel: true };
  }
  // 판정을 기다리는 몇 초 사이 이 화의 글이 바뀌었다(같은 화면의 직접 고치기일 수도 있어 "다른 곳"이라 말하지 않는다).
  if (code === "NOVEL_REVISION_CONFLICT" && action === "recheckBundle") {
    return { message: "그사이 이 화의 글이 바뀌어 다시 검사 결과를 쓰지 않았어요. 최신 내용을 불러왔어요.", shouldRefetchNovel: true };
  }
  if (code === "NOVEL_MULTI_BLOCK_EDIT_DISABLED" && action === "recheckBundle") {
    return { message: "지금은 묶음을 다시 검사할 수 없어요. 함께 버릴 수 있어요.", shouldRefetchNovel: true };
  }
  if (code === "NOVEL_JOB_NOT_APPLICABLE" && action === "dismissPatch") {
    return { message: "이미 적용했거나 버린 수정안이에요. 최신 내용을 불러왔어요.", shouldRefetchNovel: true };
  }
  if (code === "NOVEL_OUTLINE_INVALID") {
    const reason = reasonOf(error.detail);
    return {
      message: (reason === undefined ? undefined : OUTLINE_INVALID_MESSAGE[reason]) ?? "구성안을 저장하지 못했어요. 새로 불러왔어요.",
      shouldRefetchNovel: false,
    };
  }
  if (code === "NOVEL_EPISODE_OUTLINE_INVALID") {
    const reason = reasonOf(error.detail);
    return {
      message:
        (reason === undefined ? undefined : EPISODE_OUTLINE_INVALID_MESSAGE[reason]) ?? "장면 구성안을 저장하지 못했어요. 새로 불러왔어요.",
      shouldRefetchNovel: false,
    };
  }
  // 입력 견적이 서버 상한을 넘었다. 토큰 수는 이용자에게 뜻이 없어 한도 대비 비율로만 말한다. 장면 구성안은 한 화의 근거만 보내므로
  // 그 화를 나누는 것이 할 일이다.
  if (code === "NOVEL_OUTLINE_INPUT_TOO_LARGE") {
    const estimated = numberOf(error.detail, "estimatedInputTokens");
    const max = numberOf(error.detail, "maxInputTokens");
    const ratio =
      estimated === undefined || max === undefined || max <= 0 ? "" : `(한도의 ${Math.round((estimated / max) * 100).toLocaleString()}%)`;
    if (action === "episodeOutline") {
      return { message: `이 화의 대화가 너무 길어요${ratio}. 전체 구성안에서 이 화를 나눈 뒤 다시 만들어주세요.`, shouldRefetchNovel: false };
    }
    return { message: `고른 대화가 너무 길어요${ratio}. 담을 대화를 줄여 다시 승인해주세요.`, shouldRefetchNovel: false };
  }
  // 표의 문구는 구간 고르기의 말이다. 장면 구성안·원고에서 받으면 승인한 구성안의 이 화 근거가 그사이 다른 화가 됐다.
  if (code === "NOVEL_SOURCE_SECTION_LOCKED" && (action === "episodeOutline" || action === "outlineChapter")) {
    return {
      message: "이 화가 근거로 쓴 대화 중 그사이 다른 화가 된 곳이 있어요. 담을 대화와 전체 구성안을 확인해주세요.",
      shouldRefetchNovel: false,
    };
  }
  // 표의 문구는 구간 고르기의 말이다. 구성안을 만들 때 받으면 승인해 둔 선택이 그사이 화가 된 대화를 담고 있다.
  if (code === "NOVEL_SOURCE_SECTION_LOCKED" && action === "outline") {
    return {
      message: "담은 대화 중 그사이 화가 된 곳이 있어요. 담을 대화를 확인해 다시 승인해주세요.",
      shouldRefetchNovel: false,
    };
  }
  if (code === "NOVEL_ROOM_GONE" && (action === "episodeOutline" || action === "saveEpisodeOutline")) {
    return { message: "원래 대화방이 지워져 장면 구성안을 새로 만들거나 고칠 수 없어요.", shouldRefetchNovel: true };
  }
  if (code === "NOVEL_ROOM_GONE" && (action === "outline" || action === "saveOutline")) {
    return { message: "원래 대화방이 지워져 구성안을 새로 만들거나 고칠 수 없어요.", shouldRefetchNovel: true };
  }
  // 표의 문구는 화를 만들 때의 말이다. 구간 고르기에서 받으면 고를 대화 자체가 없다.
  if (code === "NOVEL_ROOM_GONE" && (action === "saveSourceSelection" || action === "approveSourceSelection")) {
    return { message: "원래 대화방이 지워져 담을 대화를 고를 수 없어요.", shouldRefetchNovel: true };
  }
  if (code === "NOVEL_BLOCK_IDS_INVALID" && action === "aiEdit") {
    return { message: "고른 문단이 바뀌었어요. 최신 내용을 불러왔어요. 다시 골라 주세요.", shouldRefetchNovel: true };
  }
  return MESSAGE_BY_CODE[code] ?? fallback(action);
}

/** 서버가 재시도 전에 주인공 이름을 먼저 받으라고 한 422 인가. 상세의 이름이 낡았을 때(다른 탭이 비웠거나 첫
 * 조회 뒤 바뀌었을 때) 장 만들기 흐름이 이름 입력으로 돌아가는 신호다. */
export function isProtagonistNameRequiredError(error: unknown): boolean {
  return isApiError(error) && error.status === 422 && detailCode(error.detail) === "NOVEL_PROTAGONIST_NAME_REQUIRED";
}

const FAILURE_SUBJECT: Record<NovelJobResponse["kind"], string> = {
  chapter_generate: "새 화를 만들지 못했어요.",
  chapter_regenerate: "화를 다시 만들지 못했어요.",
  ai_edit: "AI로 고치지 못했어요.",
  chain_generate: "남은 대화를 소설로 만들지 못했어요.",
  outline_generate: "전체 구성안을 만들지 못했어요.",
  episode_outline_generate: "장면 구성안을 만들지 못했어요.",
  outline_chapter_generate: "구성안으로 새 화를 쓰지 못했어요.",
};

/** 실패로 끝난 작업의 안내. 돌려준 클로버는 서버가 적은 환불액(`refundedAmount`)을 그대로 말한다 — 묶음·연쇄는 일부만
 * 돌려줄 수 있어 낸 금액(`chargedAmount`)과 다를 수 있다. 돌려준 것이 없으면 환불을 말하지 않는다. */
export function toNovelJobFailureMessage(job: Pick<NovelJobResponse, "kind" | "failureReason" | "refundedAmount">): string {
  return `${failureReasonSentence(job)}${toRefundSentence(job.refundedAmount)}`;
}

/** 돌려준 클로버 한 문장(앞에 띄어쓰기 포함). 없으면 빈 문자열이다. */
export function toRefundSentence(refundedAmount: number): string {
  return refundedAmount > 0 ? ` 쓴 클로버 ${refundedAmount.toLocaleString()}개는 돌려드렸어요.` : "";
}

function failureReasonSentence(job: Pick<NovelJobResponse, "kind" | "failureReason">): string {
  switch (job.failureReason) {
    case "refused":
    case "blocked":
      return `${FAILURE_SUBJECT[job.kind]} 안전 기준에 걸리는 내용이 있었어요.`;
    case "source_changed":
      if (job.kind === "ai_edit") return "고치는 동안 화가 바뀌어 수정안을 쓸 수 없게 됐어요.";
      // 구성안은 화가 아니라 승인한 담을 대화로 만든다 — 그 대화가 바뀌었으면 다시 승인해야 같은 요청이 된다.
      if (job.kind === "outline_generate") {
        return "고른 대화가 바뀌어 전체 구성안을 만들지 못했어요. 담을 대화를 확인해 다시 승인해주세요.";
      }
      if (job.kind === "episode_outline_generate") {
        return "고른 대화가 바뀌어 장면 구성안을 만들지 못했어요. 담을 대화를 확인해 다시 승인해주세요.";
      }
      if (job.kind === "outline_chapter_generate") {
        return "고른 대화가 바뀌어 원고를 쓰지 못했어요. 담을 대화를 확인해 다시 승인해주세요.";
      }
      if (job.kind === "chain_generate") return "원래 대화가 바뀌어 남은 대화를 이어 만들 수 없어요.";
      return "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.";
    // 모델이 약속한 글 형식이나 화 수를 지키지 않았다 — 같은 요청으로 다시 하면 대개 맞게 나온다.
    case "malformed":
      return `${FAILURE_SUBJECT[job.kind]} AI가 쓴 글의 형식이 맞지 않았어요.`;
    case "episode_count_mismatch":
      return `${FAILURE_SUBJECT[job.kind]} AI가 지금과 다른 화 수로 썼어요.`;
    default:
      return FAILURE_SUBJECT[job.kind];
  }
}
