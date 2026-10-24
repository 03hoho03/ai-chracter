import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, RotateCcw, X } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import { cloverKeys } from "@/entities/clover";
import {
  CHAPTER_REGENERATING_MESSAGE,
  hasNovelErrorCode,
  isChapterRegenerating,
  novelKeys,
  toNovelActionError,
  type NovelActionErrorNotice,
  type NovelAction,
  type NovelChapterResponse,
  type NovelDetailResponse,
  type NovelPendingAiEdit,
  toPendingBlockEdits,
} from "@/entities/novel";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";

import {
  useAttachIllustrationMutation,
  useDetachIllustrationMutation,
  useMoveIllustrationMutation,
  useReplaceIllustrationMutation,
} from "../api/useIllustrationPlacementMutations";
import { useSaveChapterRevisionMutation } from "../api/useSaveChapterRevisionMutation";
import {
  countIllustrationsInRange,
  isIllustrationLimitReached,
  isSameIllustrationImage,
  isUnplacedListShown,
  toActiveMove,
  toAttachTarget,
  toIllustrationActions,
  toIllustrationLabel,
  toIllustrationSpots,
  toMovedIllustrationId,
  toMoveTarget,
  toParagraphActions,
  toReplacedIllustrationId,
  toRetryAttachRequest,
  type AttachRequest,
  type BoardIllustration,
  type FailedAttach,
  type IllustrationAction,
  type IllustrationPlacement,
  type IllustrationSource,
  type MovingIllustration,
} from "../model/boardIllustrations";
import { countFreshPatchesInBlocks, toPatchLayout, type PatchUnitView } from "../model/blockEditPatches";
import {
  nextBlockSelection,
  toBlockBlockedReason,
  toBlockSelectionAnnouncement,
  toContiguousRange,
  toSceneKeyOf,
  toSelectedIndexes,
  type BlockSelectionContext,
} from "../model/blockSelection";
import {
  countChapterChars,
  isManualEditStale,
  joinParagraphRange,
  toManualEditSave,
  type ManualEditBase,
} from "../model/chapterBody";
import {
  clampParagraphRange,
  formatParagraphRange,
  isParagraphInRange,
  nextParagraphRange,
  toParagraphSelectionAnnouncement,
  type ParagraphRange,
} from "../model/paragraphRange";
import { toIllustrationUploadErrorMessage, type PickIllustrationImage } from "../model/illustrationUpload";
import { toSceneHeadings } from "../model/sceneHeadings";
import { toRecheckKey, type NovelAiEditFlow } from "../model/useNovelAiEdit";

import { AiEditPreview } from "./AiEditPreview";
import { BlockPatchCard, PatchBundleRow, PatchJobRow } from "./BlockEditPatches";
import { BoardIllustrationBlock } from "./BoardIllustrationBlock";
import { ParagraphActionRow } from "./ParagraphActionRow";
import { UnplacedIllustrationList } from "./UnplacedIllustrationList";

type NovelChapterTextProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterResponse;
  /** "고치기" 모드인가. 켜져 있을 때만 문단이 고를 수 있는 버튼이 된다. */
  isFixMode: boolean;
  aiEdit: NovelAiEditFlow;
  /** 누른 버튼이 사라지는 일(수정안 적용·버리기)이 끝난 뒤 포커스를 둘 곳 — 장 제목. */
  onFocusFallback: () => void;
  /** 직접 고치는 글이 시작할 때와 달라졌는가가 바뀔 때마다 알린다(사라질 때는 `false`). 화면이 장을 옮기기 전에
   * 이 값으로 확인을 받는다 — 장을 옮기면 이 컴포넌트가 새로 마운트돼 쓰던 글이 없어진다. */
  onDraftDirtyChange: (isDirty: boolean) => void;
  /** 삽화 스위치가 켜져 있는가(`isNovelIllustrationsOn`). 꺼져 있으면 삽화 조작·위치 확인 필요 목록이 하나도 없다 —
   * 그림 자체는 응답이 정한다(서버가 꺼짐에서 삽화 목록을 비운다). */
  isIllustrationsOn: boolean;
  /** 고치기 모드를 켜 달라는 요청. 위치 확인 필요 목록의 `놓기` 가 본문에서 놓을 문단을 고르려면 문단이 버튼이어야 한다. */
  onFixModeRequest: () => void;
  /** 붙이기·바꾸기에서 출처 하나의 창을 열어 그림을 고르게 한다. 창들은 위쪽 층(보드 위젯)이 연다. */
  onPickImage: PickIllustrationImage;
  /** 새 판의 본문을 받는 중이라 화면이 아직 옛 판을 보이는가(다시 받는 동안 옛 본문을 자리표시로 둔다). 그동안 삽화 요청을
   * 막는다 — 보이는 판을 기준으로 보내면 방금 받은 충돌을 한 번 더 받는다. */
  isRevisionRefreshing: boolean;
  /** 여러 문단 수정 스위치가 켜져 있는가(`isNovelMultiBlockEditOn`). 켜져 있으면 고치기 모드의 문단 고르기가 같은 장면 안의 떨어진
   * 문단을 하나씩 켜고 끄는 고르기가 되고, AI 수정은 블록별 수정안으로 맡긴다. 꺼져 있으면 옛 연속 범위 고르기 그대로다. 이미
   * 받은 여러 문단 수정안은 이 값과 상관없이 그 블록 자리에 보이고 적용·버릴 수 있다. */
  isMultiBlockEditOn?: boolean;
};

/** 붙이기·바꾸기 하나가 지금 어느 단계인가. 고른 그림을 올리는 중이면 `uploading`, 요청이 도는 중이면 `sending` 이다. 바꾸기면
 * 어느 그림인지(배치 id)를 든다 — 그 그림의 바꾸기 버튼에 진행을 보인다. */
type ImageRequestPhase = { phase: "uploading" | "sending"; replacingId: string | undefined };

/** 직접 고치기 하나. `base` 는 시작한 순간의 판·문단·범위라 그사이 본문이 바뀌어도 그대로다. */
type ManualEdit = { base: ManualEditBase; draft: string };

type ManualEditOutcome = "manualSaved" | "manualUnchanged" | "manualCancelled";

/** 장 본문과 그 위의 고치기 전부: 문단 고르기, 직접 고치기, AI 수정안 미리보기.
 *
 * - **읽기**: `<article>` 안 평범한 `<p>` 나열이다. 서버가 나눈 문단을 그대로 쓰고(화면이 다시 나누면 AI 수정의
 *   문단 범위가 어긋난다), 마크다운·지문 표기 해석은 하지 않는다. 이탤릭 없음, 읽기 폭은 `max-w-prose`.
 * - **고르기**: 고치기 모드에서만 문단이 `aria-pressed` 버튼이 되고, 묶음은 `role="group"` 이다. 읽다가 잘못
 *   눌러 골라지는 일이 없고, 브라우저 글자 선택을 쓰지 않아 길게 누르기·키보드 문제가 없다. 범위 규칙은
 *   `nextParagraphRange` 하나다. 고른 문단은 회색 면 + 안쪽 무채색 윤곽으로 보이고(유채색 채움 없음), 키보드
 *   포커스는 바깥 강조색 윤곽 + 링이라 둘이 색·자리로 갈리고 겹쳐도 둘 다 보인다. 무엇을 골랐는지는 항상 마운트된
 *   한 줄이 알린다.
 * - **동작 줄**: 고른 범위의 마지막 문단 바로 아래, 문서 흐름 안에 둔다. 화면 아래에 붙는 고정 막대는 이 앱의
 *   크롬 규칙(크롬 자리는 위쪽 헤더 한 줄과 넓은 화면의 좌측 패널뿐이고, 한 화면에만 두는 sticky/fixed 띠도 헤더 자리
 *   밖에 더하지 않는다 — DESIGN.md Navigation 절)에 어긋난다.
 * - **직접 고치기**: 고른 문단 자리에 입력칸이 들어선다(여덟 줄 높이에 고정되고 넘친 글은 칸 안에서
 *   스크롤된다). 시작한 순간의 판·문단·블록 id 를 잡아 두고 저장은 그 문단으로 장 전체 본문을 조립해 그 판을 기준으로
 *   보낸다(문단마다 이을 블록 id 도 함께). 그사이 판이 바뀌었으면 서버가 409 로 막고, 입력한 글은 그대로 둔다. 바뀐 판이
 *   같은 글·같은 블록이면(삽화만 바꾼 판) 그 판을 기준으로 보내 막히지 않는다.
 * - **다시 만드는 중**: 이 장을 다시 만드는 작업이 도는 동안은 직접 고치기 시작과 저장을 `aria-disabled` 로 막고
 *   사유를 단다. 다시 만든 글은 그때의 최신 판 위에 쌓여, 그사이 저장한 글을 판 이력으로 밀어낸다. 이미 열린
 *   입력칸은 닫지 않는다(쓰던 글을 지우지 않는다) — 끝나면 판이 바뀌어 저장 대신 "최신 글에서 다시"를 안내한다.
 * - **삽화**: 그림은 문단 앞·뒤 블록으로 선다(읽기 화면 스크롤 모드와 같은 블록). 고치기 모드면 그림 아래에 옮기기·떼기가
 *   있다. 옮기기는 그림의 `옮기기` → 본문에서 문단 하나를 누름 → 그 문단 아래 동작 줄의 `앞에 놓기`·`뒤에 놓기` 다(모달
 *   없이 보이는 자리에서 고른다). 지금 자리 그대로면 요청하지 않는다. 떼기는 확인 없이 바로 뗀다 — 그림 파일은 남고 판
 *   이력에서 되돌릴 수 있다. 요청은 모두 지금 판을 기준으로 가고, 판이 바뀌면 옮기는 중이 저절로 끝나 낡은 기준으로 다시
 *   보내지 않는다. 직접 고치는 범위의 그림은 입력칸 아래 한 줄로 접고, 범위 밖 그림은 그대로 고칠 수 있다(같은 글·같은
 *   블록의 새 판이라 저장이 막히지 않는다). 다시 만드는 중에는 모두 막는다 — 다시 만든 판은 문단이 모두 새것이라 놓은 자리가
 *   곧 사라진다.
 * - **붙이기·바꾸기**: 동작 줄의 `그림 붙이기` 메뉴(놓을 자리 + 출처 셋)와 그림 아래 `바꾸기` 메뉴(출처 셋)다. 출처를 고르면 그
 *   출처의 창이 열리고, 고르는 순간(기기에서 고른 그림이면 다 올린 순간) 요청한다. 붙이기는 그 순간의 지금 판을 기준으로 간다
 *   — 창을 보는 사이 판이 바뀌어도 그 문단이 남아 있으면 붙인다. 바꾸기는 한 요청이라 응답이 올 때까지 옛 그림이 그대로 서
 *   있다. 붙이기가 실패하면 같은 그림으로 다시 넣는 버튼을 두고(올린 파일을 다시 올리지 않게), 다시 넣기도 그때의 지금 판을
 *   기준으로 보낸다. 한 화의 상한(위치 확인 필요 포함)에 닿았으면 붙이기를 미리 막는다. */
export function NovelChapterText({
  novel,
  chapter,
  isFixMode,
  aiEdit,
  onFocusFallback,
  onDraftDirtyChange,
  isIllustrationsOn,
  onFixModeRequest,
  onPickImage,
  isRevisionRefreshing,
  isMultiBlockEditOn = false,
}: NovelChapterTextProps) {
  const queryClient = useQueryClient();
  const groupLabelId = useId();
  const editorId = useId();
  const actionBlockedReasonId = useId();
  const outsideSceneReasonId = useId();
  const blockLimitReasonId = useId();
  const paragraphs = chapter.revision.paragraphs;
  const [range, setRange] = useState<ParagraphRange | null>(null);
  // 여러 문단 고르기(스위치 켜짐)의 고른 블록 id — 누른 차례이고 마지막이 Shift 이어 고르기의 시작점이다. 블록 id 라 다른 곳의
  // 수정으로 문단 차례가 바뀌어도 같은 문단을 가리킨다(지워진 블록은 아래에서 빠진다).
  const [blockSelection, setBlockSelection] = useState<string[]>([]);
  const [manualEdit, setManualEdit] = useState<ManualEdit | null>(null);
  // 저장 실패 문장. 저장을 누른 순간에 기록하고 다음 저장·취소에서만 지운다 — 409 뒤 상세를 다시 받아도 남는다.
  const [editError, setEditError] = useState<string | undefined>(undefined);
  // 고르기를 알리는 한 줄. 일이 일어난 순간에 기록한다. 직접 고치기의 결과는 여기가 아니라 장 머리 아래 결과
  // 문장(`aiEdit.report`)에 남긴다 — 두 줄에 나눠 남기면 한쪽의 지난 결과가 다른 쪽의 새 결과 옆에 남는다.
  const [liveMessage, setLiveMessage] = useState("");
  const saveMutation = useSaveChapterRevisionMutation();
  const paragraphButtonsRef = useRef(new Map<number, HTMLButtonElement>());
  const pendingFocusIndexRef = useRef<number | undefined>(undefined);
  // 옮기기를 시작한 그림. 판이 바뀌면 `activeMove` 가 저절로 비므로 이 값을 지우는 효과가 없다.
  const [moving, setMoving] = useState<MovingIllustration | null>(null);
  // 삽화 요청 실패 문장. 다음 삽화 조작에서만 지운다 — 충돌 뒤 상세를 다시 받아도 남는다.
  const [placementError, setPlacementError] = useState<string | undefined>(undefined);
  const moveMutation = useMoveIllustrationMutation();
  const detachMutation = useDetachIllustrationMutation();
  const attachMutation = useAttachIllustrationMutation();
  const replaceMutation = useReplaceIllustrationMutation();
  // 붙이기·바꾸기의 단계. 업로드는 뮤테이션이 아니라 이 상태가 진행을 든다.
  const [imageRequest, setImageRequest] = useState<ImageRequestPhase | undefined>(undefined);
  // 실패한 붙이기 — 같은 그림으로 다시 넣기에 쓴다. 다음 붙이기를 시작하거나 다시 넣기가 성공하면 지운다. 옮기기·떼기·바꾸기는
  // 지우지 않는다 — 상한에 막힌 뒤 다른 삽화를 떼고 다시 넣는 것이 이 버튼의 쓰임이다.
  const [failedAttach, setFailedAttach] = useState<FailedAttach | null>(null);
  // 창을 보는 사이·올리는 사이 판이 바뀔 수 있다 — 붙이기는 그 순간의 지금 판을 기준으로 보내려고 렌더마다 최신 판을 둔다.
  const revisionRef = useRef(chapter.revision);
  revisionRef.current = chapter.revision;
  // 그림 블록과 위치 확인 필요 항목(배치 id 로). 성공한 옮기기 뒤 옮긴 그림으로 포커스를 보낸다.
  const figureRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingFigureFocusRef = useRef<string | undefined>(undefined);

  // 다른 곳의 수정을 다시 받아 문단 수가 줄었으면 범위를 남은 문단 안으로 접는다.
  const activeRange = isFixMode ? clampParagraphRange(range, paragraphs.length) : null;
  // 입력칸을 놓을 자리. 범위는 시작한 판의 것이라, 다른 곳의 수정으로 문단 수가 줄었으면 남은 문단 안으로 접는다.
  const editRange = manualEdit ? clampParagraphRange(manualEdit.base.range, paragraphs.length) : null;
  // 시작한 뒤 판이 바뀌었는가. 그러면 저장은 서버가 충돌로 막고, 입력칸 자리의 새 글은 입력칸에 가려 보이지 않는다. 같은
  // 글·같은 블록의 새 판(삽화만 바꾼 판)은 그 판 위에 저장하므로 낡지 않았다.
  const isEditStale = manualEdit !== null && isManualEditStale(manualEdit.base, chapter.revision);
  const isDraftDirty =
    manualEdit !== null && manualEdit.draft !== joinParagraphRange(manualEdit.base.paragraphs, manualEdit.base.range);
  const pendingEdits = novel.pendingAiEdits.filter((edit) => edit.chapterId === chapter.id);
  const blockIds = chapter.revision.blocks.map((block) => block.id);
  const blockEdits = toPendingBlockEdits(novel, chapter.id);
  // 여러 문단 수정안은 그 블록 자리에 문단 대신 선다. 그 자리는 고르기 버튼이 아니다.
  const patchLayout = toPatchLayout(blockEdits, blockIds);
  const selectionContext: BlockSelectionContext = {
    blockIds,
    sceneKeyOf: toSceneKeyOf(chapter.revision),
    maxBlocks: novel.limits.blockEditMaxBlocks,
    isSelectable: (index) => !patchLayout.cardBlockIndexes.has(index),
  };
  const isSaving = saveMutation.isPending;
  // 다시 만들기는 묶음 단위라 이 화가 든 묶음을 상세 목차에서 찾는다(화 본문 응답에는 묶음이 없다).
  const batchId = novel.chapters.find((item) => item.id === chapter.id)?.batchId;
  const isRegenerating = isChapterRegenerating(novel.activeJob, chapter.id, batchId);
  const spots = toIllustrationSpots(chapter.revision);
  const activeMove = toActiveMove({ isIllustrationsOn, moving, revision: chapter.revision });
  // 여러 문단 고르기는 스위치가 켜진 고치기 모드에서, 삽화를 옮기는 중이 아닐 때만이다(놓을 자리는 문단 하나).
  const isBlockMode = isMultiBlockEditOn && isFixMode && activeMove === null;
  const selectedIndexes = isBlockMode
    ? toSelectedIndexes(blockSelection, blockIds).filter((index) => selectionContext.isSelectable(index))
    : [];
  const selectedBlockIds = selectedIndexes.map((index) => blockIds[index]).filter((id) => id !== undefined);
  // 장면 경계가 있는 화(구성안으로 쓴 화)의 장면 머리줄. 같은 장면 안에서만 함께 고르는 규칙이 스위치 뒤라 머리줄도 스위치 뒤다.
  const sceneHeadings = isMultiBlockEditOn ? toSceneHeadings(chapter.revision) : new Map<number, never>();
  const selectedSceneKey = selectedBlockIds[0] === undefined ? undefined : selectionContext.sceneKeyOf(selectedBlockIds[0]);
  // 직접 고치기·그림 붙이기는 이어진 문단에만 된다 — 여러 문단 고르기에서는 고른 것이 이어져 있을 때의 범위다.
  const actionRange = isBlockMode ? toContiguousRange(selectedIndexes) : activeRange;
  const isPlacing = moveMutation.isPending || detachMutation.isPending || imageRequest !== undefined;
  // 직접 고치기 저장과 삽화 요청은 같은 판을 기준으로 가므로 한쪽이 도는 동안 다른 쪽을 막는다 — 둘이 함께 나가면 늦은 쪽이
  // 같은 화면의 요청과 충돌해 409 로 끝난다.
  const isPlacementBlocked = isPlacing || isRegenerating || isSaving || isRevisionRefreshing;

  useEffect(() => {
    onDraftDirtyChange(isDraftDirty);
    // 알릴 시점은 값이 바뀐 순간이다. 콜백은 호출부의 ref 쓰기라 렌더마다 같은 일을 한다.
  }, [isDraftDirty]);
  useEffect(() => () => onDraftDirtyChange(false), []);

  // 모드를 끄면 고른 것도 푼다(입력 중인 직접 고치기는 그대로 둔다 — 쓰던 글을 지우지 않는다). 옮기기도 끝난다.
  useEffect(() => {
    if (isFixMode) return;
    setRange(null);
    setBlockSelection([]);
    setMoving(null);
    setLiveMessage("");
  }, [isFixMode]);

  // 옮기는 동안 Esc 는 어디서 눌러도 옮기기만 그만둔다. 보드도 Esc 로 고른 화를 푸는데(편집 패널이 닫힌다) 그쪽은 React
  // 처리기라 문서에 버블로 걸면 늦는다 — 캡처로 먼저 받아 기본 동작을 막고, 패널은 막힌 Esc 를 무시한다.
  useEffect(() => {
    if (activeMove === null) return;
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // 그사이 연 대화상자(판 이력 등)의 Esc 는 그 대화상자 몫이다.
      if (event.target instanceof Element && event.target.closest('[role="dialog"],[role="alertdialog"]')) return;
      event.preventDefault();
      cancelMove();
    }
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
    // 옮기는 그림이 바뀔 때만 다시 건다. 처리기는 상태 설정과 ref 만 쓴다.
  }, [activeMove?.id]);

  // 옮긴 그림은 새 판에서 배치 id 가 바뀌어 새로 그려진다 — 그 블록이 그려진 렌더 뒤에 포커스를 옮긴다. 응답을 캐시에 쓰는
  // 렌더와 요청이 끝나는 순간의 앞뒤가 정해져 있지 않아 렌더마다 본다.
  useEffect(() => {
    const id = pendingFigureFocusRef.current;
    if (id === undefined) return;
    const element = figureRefs.current.get(id);
    if (element === undefined) return;
    pendingFigureFocusRef.current = undefined;
    element.focus();
  });

  // 입력칸이 닫힌 뒤(저장·취소) 그 자리의 첫 문단 버튼으로 포커스를 돌린다. 버튼은 입력칸이 사라진 다음 렌더에
  // 생기므로 렌더 뒤에 옮긴다. 고치기 모드가 꺼져 있으면 문단이 버튼이 아니라 장 제목으로 간다.
  useEffect(() => {
    const index = pendingFocusIndexRef.current;
    if (index === undefined || manualEdit !== null) return;
    pendingFocusIndexRef.current = undefined;
    const button = paragraphButtonsRef.current.get(Math.min(index, paragraphs.length - 1));
    if (button) {
      button.focus();
      return;
    }
    onFocusFallback();
    // 옮길 시점은 입력칸이 닫힌 렌더 하나다.
  }, [manualEdit]);

  function select(index: number, extend: boolean) {
    if (activeMove !== null) {
      // 놓을 자리는 문단 하나다 — 범위 늘리기(Shift)는 받지 않는다. 고른 문단을 다시 누르면 푼다.
      const isSame = activeRange !== null && activeRange.start === index && activeRange.end === index;
      setRange(isSame ? null : { start: index, end: index });
      setLiveMessage(isSame ? "고른 문단이 없어요." : `${index + 1}번째 문단을 골랐어요. 앞이나 뒤에 놓으세요.`);
      return;
    }
    if (isBlockMode) {
      // 누른 차례를 지켜 넘긴다 — 마지막으로 누른 문단이 Shift 이어 고르기의 시작점이다(본문 차례로 정렬하면 맨 뒤 문단이 된다).
      const clicked = blockSelection.filter((id) => selectedBlockIds.includes(id));
      const step = nextBlockSelection(clicked, index, { extend }, selectionContext);
      setBlockSelection(step.selection);
      setLiveMessage(
        toBlockSelectionAnnouncement(toSelectedIndexes(step.selection, blockIds), step.outcome, selectionContext.maxBlocks),
      );
      return;
    }
    const next = nextParagraphRange(activeRange, index, { extend });
    setRange(next);
    setLiveMessage(toParagraphSelectionAnnouncement(next));
  }

  function setFigureRef(id: string, element: HTMLDivElement | null) {
    if (element) figureRefs.current.set(id, element);
    else figureRefs.current.delete(id);
  }

  function startMove(illustration: BoardIllustration) {
    setPlacementError(undefined);
    setMoving({ illustrationId: illustration.id, revisionId: chapter.revision.id });
    setRange(null);
    setBlockSelection([]);
    setLiveMessage("놓을 문단을 누르세요. 그 문단 앞이나 뒤에 놓을 수 있어요. Esc 로 취소해요.");
  }

  /** 위치 확인 필요 목록의 `놓기` — 문단이 고를 수 있는 버튼이 되도록 고치기 모드를 켜고 옮기기를 시작한다. */
  function startPlaceUnplaced(illustration: BoardIllustration) {
    if (!isFixMode) onFixModeRequest();
    startMove(illustration);
  }

  function cancelMove(message = "옮기기를 그만뒀어요.") {
    const id = activeMove?.id;
    setMoving(null);
    setRange(null);
    setLiveMessage(message);
    // 동작 줄이 사라지며 누른 버튼도 사라진다 — 옮기던 그림으로 포커스를 돌린다.
    if (id !== undefined) figureRefs.current.get(id)?.focus();
  }

  async function place(paragraphIndex: number, placement: IllustrationPlacement) {
    if (activeMove === null || isPlacementBlocked) return;
    const target = toMoveTarget(chapter.revision, activeMove, paragraphIndex, placement);
    if (target === null) {
      cancelMove("지금 자리와 같아 옮기지 않았어요.");
      return;
    }
    setPlacementError(undefined);
    try {
      const next = await moveMutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        illustrationId: activeMove.id,
        baseRevisionId: chapter.revision.id,
        target,
      });
      pendingFigureFocusRef.current = toMovedIllustrationId(next.revision, target);
      setMoving(null);
      setRange(null);
      setLiveMessage(`삽화를 ${paragraphIndex + 1}번째 문단 ${placement === "before" ? "앞으로" : "뒤로"} 옮겼어요.`);
    } catch (error) {
      handlePlacementError(error, "moveIllustration");
    }
  }

  /** 그림 하나를 뗀다. 문단 사이 그림이면 그 문단으로, 위치 확인 필요 그림이면 장 제목으로 포커스를 옮긴다 — 누른 버튼은
   * 그림과 함께 사라진다. */
  async function detach(illustration: BoardIllustration, paragraphIndex: number | undefined) {
    if (isPlacementBlocked) return;
    setPlacementError(undefined);
    try {
      await detachMutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        illustrationId: illustration.id,
        baseRevisionId: chapter.revision.id,
      });
      setMoving(null);
      setRange(null);
      setLiveMessage("삽화를 뗐어요. 판 이력에서 되돌릴 수 있어요.");
      const button = paragraphIndex === undefined ? undefined : paragraphButtonsRef.current.get(paragraphIndex);
      if (button) button.focus();
      else onFocusFallback();
    } catch (error) {
      handlePlacementError(error, "detachIllustration");
    }
  }

  /** 삽화 요청 실패. 옮기기를 끝내고(다시 받은 판에서 그림 id 가 바뀐다) 문장을 남긴다. 충돌·없어진 그림이면 상세를 다시
   * 받아 화 키가 새 판으로 바뀌고 본문을 새로 받는다 — 다음 요청은 그 판을 기준으로 간다. 스위치가 꺼졌으면 가격도 다시 받아
   * 삽화 조작을 거둔다. */
  function handlePlacementError(error: unknown, action: NovelAction): NovelActionErrorNotice | null {
    setMoving(null);
    setRange(null);
    setBlockSelection([]);
    setLiveMessage("");
    // 다시 받은 판에서는 배치 id 가 바뀌어 누른 그림도 새로 그려진다 — 사라지지 않는 장 제목으로 옮긴다.
    onFocusFallback();
    const result = toNovelActionError(error, action);
    // 재동의가 필요하면 전역 재동의 모달이 맡는다.
    if (result === null) return null;
    setPlacementError(result.message);
    if (hasNovelErrorCode(error, "NOVEL_ILLUSTRATIONS_DISABLED")) {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
      // 판이 그대로라 상세를 다시 받아도 화 키가 같다 — 꺼짐에서 서버가 비워 주는 삽화 목록을 받으려면 화도 다시 받는다.
      void queryClient.invalidateQueries({ queryKey: novelKeys.chapter(novel.id, chapter.id, chapter.revision.id) });
    }
    // 원작 그림을 쓸 수 없게 됐으면(그사이 원작 이용 제한) 다음에 창을 열 때 후보도 새로 받는다.
    if (hasNovelErrorCode(error, "NOVEL_ILLUSTRATION_ASSET_INVALID")) {
      void queryClient.invalidateQueries({ queryKey: novelKeys.illustrationCandidates(novel.id) });
    }
    if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    return result;
  }

  /** 고른 출처의 창을 열어 그림을 받고, 기기에서 고른 파일이면 올려 자산 id 로 바꾼다. 고르지 않았거나 업로드가 실패하면
   * `undefined`(실패 문장은 여기서 남긴다). */
  async function pickAsset(
    source: IllustrationSource,
    replacingId: string | undefined,
    currentAssetId: string | undefined,
  ): Promise<{ assetId: string; source: IllustrationSource } | undefined> {
    const picked = await onPickImage(source, { currentAssetId });
    if (picked === undefined) return undefined;
    if (picked.kind === "asset") return { assetId: picked.assetId, source: picked.source };
    setImageRequest({ phase: "uploading", replacingId });
    try {
      return { assetId: await uploadAsset(picked.upload.file, "novel-illustration"), source: "upload" };
    } catch (error) {
      setImageRequest(undefined);
      setPlacementError(toIllustrationUploadErrorMessage(error));
      return undefined;
    }
  }

  /** 고른 범위의 앞·뒤에 그림을 붙인다. */
  async function attach(source: IllustrationSource, placement: IllustrationPlacement) {
    if (actionRange === null || isPlacementBlocked || isIllustrationLimitReached(chapter.revision)) return;
    const target = toAttachTarget(chapter.revision, actionRange, placement);
    if (target === null) return;
    setPlacementError(undefined);
    const asset = await pickAsset(source, undefined, undefined);
    if (asset === undefined) return;
    // 실패한 붙이기 기록은 새 그림을 실제로 고른 뒤에 지운다 — 창을 열었다 그냥 닫으면 다시 넣기가 남는다.
    setFailedAttach(null);
    await sendAttach({ ...asset, target });
  }

  /** 붙이기 요청 하나 — 처음 붙이기와 실패 뒤 다시 넣기가 함께 쓴다. 기준은 보내는 순간의 지금 판이다. */
  async function sendAttach(failed: FailedAttach) {
    const request = toRetryAttachRequest(revisionRef.current, failed);
    if (request === null) {
      // 창을 보는 사이 그 문단이 지워졌다 — 보내면 422 다. 다시 고르게 한다(다시 넣기 자리에도 같은 안내가 선다).
      setImageRequest(undefined);
      setFailedAttach(failed);
      setLiveMessage("고른 문단이 바뀌어 붙이지 않았어요. 문단을 다시 골라 주세요.");
      return;
    }
    setImageRequest({ phase: "sending", replacingId: undefined });
    try {
      const next = await attachMutation.mutateAsync({ ...request, novelId: novel.id, chapterId: chapter.id });
      pendingFigureFocusRef.current = toMovedIllustrationId(next.revision, request.target);
      setFailedAttach(null);
      setRange(null);
      setBlockSelection([]);
      setLiveMessage(toAttachedMessage(next.revision.blocks, request));
    } catch (error) {
      const result = handlePlacementError(error, "attachIllustration");
      // 다시 넣어도 같은 결과인 실패(쓸 수 없는 그림·삽화가 꺼짐)와 재동의는 다시 넣기를 두지 않는다.
      const isRetryable =
        result !== null &&
        !hasNovelErrorCode(error, "NOVEL_ILLUSTRATION_ASSET_INVALID") &&
        !hasNovelErrorCode(error, "NOVEL_ILLUSTRATIONS_DISABLED");
      setFailedAttach(isRetryable ? failed : null);
    } finally {
      setImageRequest(undefined);
    }
  }

  async function retryAttach() {
    if (failedAttach === null || isPlacementBlocked) return;
    setPlacementError(undefined);
    await sendAttach(failedAttach);
  }

  /** 그림 하나를 다른 그림으로 바꾼다. 고르기 시작한 판의 배치 id 와 그 판을 함께 보낸다 — 배치 id 는 판마다 새로 매겨져 옛
   * id 를 새 판에 보낼 수 없다. 그사이 판이 바뀌었으면 서버가 충돌로 막고 다시 받는다. */
  async function replace(illustration: BoardIllustration, source: IllustrationSource) {
    if (isPlacementBlocked) return;
    const baseRevisionId = chapter.revision.id;
    setPlacementError(undefined);
    setMoving(null);
    const asset = await pickAsset(source, illustration.id, illustration.assetId);
    if (asset === undefined) return;
    if (isSameIllustrationImage(illustration, asset)) {
      // 지금 그림을 그대로 골랐다 — 보내면 서버는 같은 배치의 새 판을 하나 더 쌓는다(판 이력에 빈 판이 는다).
      setImageRequest(undefined);
      setLiveMessage("지금 삽화와 같아 바꾸지 않았어요.");
      return;
    }
    setImageRequest({ phase: "sending", replacingId: illustration.id });
    try {
      const next = await replaceMutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        illustrationId: illustration.id,
        baseRevisionId,
        ...asset,
      });
      pendingFigureFocusRef.current = toReplacedIllustrationId(next.revision, illustration);
      setLiveMessage("삽화를 바꿨어요. 판 이력에서 되돌릴 수 있어요.");
    } catch (error) {
      handlePlacementError(error, "replaceIllustration");
    } finally {
      setImageRequest(undefined);
    }
  }

  function replacePendingLabelOf(illustrationId: string): string | undefined {
    return imageRequest?.replacingId === illustrationId ? toPhaseLabel(imageRequest, "바꾸는 중…") : undefined;
  }

  function pendingActionOf(illustrationId: string): IllustrationAction | undefined {
    if (moveMutation.isPending && moveMutation.variables.illustrationId === illustrationId) return "move";
    if (detachMutation.isPending && detachMutation.variables.illustrationId === illustrationId) return "detach";
    return undefined;
  }

  function renderIllustrations(items: readonly BoardIllustration[], paragraphIndex: number, placement: IllustrationPlacement) {
    return items.map((illustration, rank) => (
      <BoardIllustrationBlock
        key={illustration.id}
        ref={(element) => setFigureRef(illustration.id, element)}
        illustration={illustration}
        paragraphIndex={paragraphIndex}
        placement={placement}
        label={toIllustrationLabel({ paragraphIndex, placement, rank, count: items.length })}
        actions={toIllustrationActions({ isIllustrationsOn, isFixMode, illustration })}
        isMoving={activeMove?.id === illustration.id}
        isIllustrationsOn={isIllustrationsOn}
        isRegenerating={isRegenerating}
        isBusy={isPlacementBlocked}
        pendingAction={pendingActionOf(illustration.id)}
        replacePendingLabel={replacePendingLabelOf(illustration.id)}
        onMove={() => startMove(illustration)}
        onCancelMove={() => cancelMove()}
        onReplace={(source) => void replace(illustration, source)}
        onDetach={() => void detach(illustration, paragraphIndex)}
      />
    ));
  }

  function clearSelection(focusIndex: number) {
    setRange(null);
    setBlockSelection([]);
    setLiveMessage("고른 문단을 풀었어요.");
    // 동작 줄이 사라지며 누른 버튼도 사라진다 — 마지막으로 고른 문단으로 포커스를 옮겨 둔다.
    paragraphButtonsRef.current.get(focusIndex)?.focus();
  }

  function startManualEdit(target: ParagraphRange) {
    aiEdit.report({ type: "started" });
    setEditError(undefined);
    setManualEdit({
      base: {
        revisionId: chapter.revision.id,
        paragraphs,
        blockIds: chapter.revision.blocks.map((block) => block.id),
        range: target,
      },
      draft: joinParagraphRange(paragraphs, target),
    });
    setRange(null);
    setBlockSelection([]);
    setLiveMessage("");
  }

  function closeManualEdit(outcome: ManualEditOutcome) {
    if (editRange) pendingFocusIndexRef.current = editRange.start;
    setManualEdit(null);
    setEditError(undefined);
    setLiveMessage("");
    aiEdit.report({ type: outcome, chapterOrdinal: chapter.ordinal });
  }

  async function saveManualEdit() {
    if (isSaving || isPlacing || isRegenerating || manualEdit === null || editRange === null) return;
    aiEdit.report({ type: "started" });
    setEditError(undefined);
    const { baseRevisionId, body, blockIds, isUnchanged } = toManualEditSave(
      manualEdit.base,
      manualEdit.draft,
      chapter.revision,
    );
    const length = countChapterChars(body);
    if (length === 0) {
      setEditError("화 본문을 모두 비울 수는 없어요.");
      return;
    }
    if (length > novel.limits.chapterBodyMaxLength) {
      setEditError(`화 본문은 ${novel.limits.chapterBodyMaxLength.toLocaleString()}자까지 쓸 수 있어요.`);
      return;
    }
    if (isUnchanged) {
      closeManualEdit("manualUnchanged");
      return;
    }
    try {
      await saveMutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        baseRevisionId,
        body,
        blockIds,
      });
      closeManualEdit("manualSaved");
    } catch (error) {
      const result = toNovelActionError(error, "edit");
      // 재동의가 필요하면 전역 재동의 모달이 맡는다 — 입력칸은 그대로 두어 동의 뒤 다시 저장할 수 있다.
      if (result === null) return;
      setEditError(result.message);
      if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  async function startAiEdit(target: ParagraphRange) {
    const isStarted = await aiEdit.start({
      chapterId: chapter.id,
      chapterOrdinal: chapter.ordinal,
      revisionId: chapter.revision.id,
      paragraphs,
      range: target,
    });
    if (!isStarted) return;
    // 작업을 맡겼으면 고른 것을 푼다 — 수정안은 끝나면 그 문단 아래에 온다. 사라지는 동작 줄 대신 고른 범위의 첫
    // 문단으로 포커스를 둔다.
    setRange(null);
    setLiveMessage("");
    paragraphButtonsRef.current.get(target.start)?.focus();
  }

  /** 고른 블록들을 여러 문단 수정으로 맡긴다. 맡겼으면 고른 것을 풀고 고른 첫 문단으로 포커스를 둔다(사라지는 동작 줄 대신). */
  async function startBlockEdit(indexes: readonly number[]) {
    const isStarted = await aiEdit.startBlocks({
      chapterId: chapter.id,
      chapterOrdinal: chapter.ordinal,
      revisionId: chapter.revision.id,
      paragraphs,
      blockIds: indexes.map((index) => blockIds[index]).filter((id) => id !== undefined),
      indexes,
    });
    if (!isStarted) return;
    setBlockSelection([]);
    setLiveMessage("");
    const first = indexes[0];
    if (first !== undefined) paragraphButtonsRef.current.get(first)?.focus();
  }

  async function handlePreviewAction(action: () => Promise<void>) {
    await action();
    // 적용하든 버리든 그 수정안 상자가 사라지며 누른 버튼도 사라진다 — 결과 안내가 있는 장 머리로 옮긴다.
    onFocusFallback();
  }

  /** 묶음 다시 검사. 따로 적용해도 된다는 판정이면 묶음이 풀려 누른 버튼이 사라지므로 장 머리로 포커스를 옮기고, 아니면(판정이
   * 묶음 유지이거나 실패) 버튼이 남아 포커스를 그대로 둔다 — 결과는 안내 줄이 알린다. */
  async function recheckBundle(unit: PatchUnitView) {
    if (await aiEdit.recheckBundle(unit, chapter.ordinal)) onFocusFallback();
  }

  function previewsEndingAt(index: number): NovelPendingAiEdit[] {
    const lastIndex = paragraphs.length - 1;
    return pendingEdits.filter((edit) => Math.min(edit.paragraphEnd, lastIndex) === index);
  }

  /** 문단 하나의 자리: 직접 고치는 범위면 그 첫 자리에 입력칸(나머지 자리는 비움), 고치기 모드면 고를 수 있는 버튼,
   * 아니면 평범한 문단. */
  function renderParagraph(paragraph: string, index: number) {
    if (editRange !== null && manualEdit !== null && isParagraphInRange(editRange, index)) {
      if (index !== editRange.start) return null;
      return (
        <ManualEditor
          id={editorId}
          rangeLabel={formatParagraphRange(editRange)}
          draft={manualEdit.draft}
          error={editError}
          isStale={isEditStale}
          isRegenerating={isRegenerating}
          hasPendingAiEdits={pendingEdits.length > 0}
          hasPendingPatches={
            countFreshPatchesInBlocks(
              blockEdits,
              new Set(manualEdit.base.blockIds.slice(manualEdit.base.range.start, manualEdit.base.range.end + 1)),
            ) > 0
          }
          illustrationCount={countIllustrationsInRange(spots, editRange)}
          isSaving={isSaving}
          isPlacing={isPlacing}
          onDraftChange={(draft) => setManualEdit((current) => (current ? { ...current, draft } : current))}
          onCancel={() => closeManualEdit("manualCancelled")}
          onSave={() => void saveManualEdit()}
        />
      );
    }
    if (isFixMode) {
      return (
        <ParagraphButton
          ref={(element) => {
            if (element) paragraphButtonsRef.current.set(index, element);
            else paragraphButtonsRef.current.delete(index);
          }}
          text={paragraph}
          isSelected={isBlockMode ? selectedIndexes.includes(index) : isParagraphInRange(activeRange, index)}
          blockedReasonId={isBlockMode ? toBlockedReasonId(index) : undefined}
          onSelect={(extend) => select(index, extend)}
        />
      );
    }
    return <p className="-mx-2 px-2 py-1 whitespace-pre-line">{paragraph}</p>;
  }

  /** 여러 문단 고르기에서 그 문단을 지금 고를 수 없는 까닭 문장의 id. */
  function toBlockedReasonId(index: number): string | undefined {
    const reason = toBlockBlockedReason(index, selectedBlockIds, selectionContext);
    if (reason === "outsideScene") return outsideSceneReasonId;
    return reason === "limit" ? blockLimitReasonId : undefined;
  }

  const isAiBlocked = aiEdit.isBlocked;
  // 이 장을 다시 만드는 중이면 AI 수정도 막혀 있다(진행 중 작업은 하나) — 두 버튼의 사유를 한 문장으로 말한다.
  const actionBlockedReason = isRegenerating ? CHAPTER_REGENERATING_MESSAGE : toAiBlockedReason(aiEdit);
  const groupLabel = activeMove === null ? "고칠 문단 고르기" : "삽화를 놓을 문단 고르기";
  // 동작 줄의 붙이기 버튼에 보일 진행. 바꾸기의 진행은 그 그림의 바꾸기 버튼이 보인다.
  const attachPendingLabel = imageRequest?.replacingId === undefined ? toPhaseLabel(imageRequest, "붙이는 중…") : undefined;

  return (
    <div className="flex flex-col gap-3">
      {isFixMode && (
        <div className="flex flex-col gap-1">
          <p id={groupLabelId} className="text-sm break-keep text-muted-foreground">
            {isMultiBlockEditOn
              ? `고칠 문단을 눌러 고르세요. 같은 장면 안이면 떨어진 문단도 함께 고를 수 있어요(한 번에 ${novel.limits.blockEditMaxBlocks}개까지). Shift를 누른 채 누르면 사이 문단까지 골라요.`
              : "고칠 문단을 눌러 고르세요. 이어진 문단을 함께 고를 수 있어요."}
          </p>
          {isBlockMode && blockIds.some((_, index) => toBlockBlockedReason(index, selectedBlockIds, selectionContext) === "outsideScene") && (
            <p id={outsideSceneReasonId} className="text-sm break-keep text-muted-foreground">
              다른 장면의 문단은 함께 고를 수 없어요. 다른 장면을 고치려면 고른 문단을 먼저 풀어 주세요.
            </p>
          )}
          {isBlockMode && selectedBlockIds.length >= selectionContext.maxBlocks && (
            <p id={blockLimitReasonId} className="text-sm break-keep text-muted-foreground">
              {`한 번에 ${selectionContext.maxBlocks}개 문단까지 고를 수 있어요. 고른 문단을 풀면 다른 문단을 고를 수 있어요.`}
            </p>
          )}
        </div>
      )}
      {/* 항상 마운트된 알림 줄 — 조건부로 붙이면 붙는 순간의 문장을 화면 낭독기가 놓친다. */}
      <p aria-live="polite" aria-atomic className="text-sm break-keep text-muted-foreground empty:sr-only">
        {liveMessage || null}
      </p>
      {placementError !== undefined && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {placementError}
        </p>
      )}
      {isIllustrationsOn && failedAttach !== null && (
        <RetryAttachRow
          canRetry={toRetryAttachRequest(chapter.revision, failedAttach) !== null}
          isBlocked={isPlacementBlocked}
          isLimitReached={isIllustrationLimitReached(chapter.revision)}
          isRetrying={imageRequest?.phase === "sending" && imageRequest.replacingId === undefined}
          onRetry={() => void retryAttach()}
        />
      )}
      {isUnplacedListShown({ isIllustrationsOn, revision: chapter.revision }) && (
        <UnplacedIllustrationList
          illustrations={spots.unplaced}
          movingId={activeMove?.id}
          isRegenerating={isRegenerating}
          isBusy={isPlacementBlocked}
          detachingId={detachMutation.isPending ? detachMutation.variables.illustrationId : undefined}
          rowRef={setFigureRef}
          // 목록은 고치기 모드와 상관없이 서지만, 항목마다 할 수 있는 일은 문단 사이 그림과 같은 판정이다(내린 그림은 떼기만).
          actionsOf={(illustration) => toIllustrationActions({ isIllustrationsOn, isFixMode: true, illustration })}
          onPlace={startPlaceUnplaced}
          onCancelMove={() => cancelMove()}
          onDetach={(illustration) => void detach(illustration, undefined)}
        />
      )}

      <article className="flex max-w-prose flex-col text-sm leading-relaxed break-keep text-foreground">
        <div
          role={isFixMode ? "group" : undefined}
          aria-label={isFixMode ? groupLabel : undefined}
          aria-describedby={isFixMode ? groupLabelId : undefined}
          className="flex flex-col gap-3"
        >
          {paragraphs.map((paragraph, index) => {
            // 옮기는 중이면 직접 고치는 입력칸이 열려 있어도 범위 밖 문단에 놓을 수 있다(같은 글·같은 블록의 새 판이라
            // 저장이 막히지 않는다).
            const isActionRowHere = isBlockMode
              ? selectedIndexes.at(-1) === index && manualEdit === null
              : activeRange !== null && activeRange.end === index && (manualEdit === null || activeMove !== null);
            const cards = patchLayout.cardsAt.get(index);
            // 직접 고치는 범위의 그림은 입력칸이 대신하는 자리라 그리지 않고 입력칸 아래 한 줄로 접는다.
            const isInEditRange = editRange !== null && manualEdit !== null && isParagraphInRange(editRange, index);
            const sceneHeading = sceneHeadings.get(index);
            return (
              // 서버가 준 문단 순서가 곧 정체성이다(문단에 안정 id 가 없다 — 고르기 범위도 같은 인덱스를 쓴다).
              <Fragment key={index}>
                {/* 장면 머리줄은 앞 그림과 같은 칸에 넣는다 — 칸을 하나 더 두면 머리줄이 없는 화면(스위치 꺼짐)에서도 뒤 형제의 자리가
                    밀려 `useId` 값이 바뀐다. */}
                {sceneHeading === undefined
                  ? !isInEditRange && renderIllustrations(spots.before[index] ?? [], index, "before")
                  : [
                      <h3
                        key="scene-heading"
                        className={cn("text-xs font-medium break-keep text-muted-foreground", index > 0 && "pt-3")}
                      >
                        {sceneHeading.label}
                        {isBlockMode && selectedSceneKey !== undefined && selectedSceneKey !== sceneHeading.sceneKey
                          ? " · 다른 장면이라 함께 고를 수 없어요"
                          : null}
                      </h3>,
                      ...(isInEditRange ? [] : renderIllustrations(spots.before[index] ?? [], index, "before")),
                    ]}
                {cards !== undefined && !isInEditRange
                  ? cards.map((card) => (
                      <BlockPatchCard
                        key={card.patch.id}
                        card={card}
                        currentText={paragraph}
                        isActing={aiEdit.actingEditId !== undefined}
                        onApply={(unit) => void handlePreviewAction(() => aiEdit.applyPatchUnit(unit, chapter.ordinal))}
                        onDismiss={(unit) => void handlePreviewAction(() => aiEdit.dismissPatches({ unit }, chapter.ordinal))}
                      />
                    ))
                  : renderParagraph(paragraph, index)}

                {isActionRowHere && activeMove !== null && (
                  <MoveTargetRow
                    isBlocked={isPlacementBlocked}
                    blockedReasonId={isRegenerating ? actionBlockedReasonId : undefined}
                    pendingPlacement={moveMutation.isPending ? moveMutation.variables.target.placement : undefined}
                    onPlace={(placement) => void place(index, placement)}
                    onCancel={() => cancelMove()}
                  />
                )}

                {isActionRowHere && activeMove === null && isBlockMode && (
                  <>
                    <ParagraphActionRow
                      actions={toParagraphActions({ isMoving: false, isIllustrationsOn }).filter(
                        (action) => actionRange !== null || (action !== "manualEdit" && action !== "attach"),
                      )}
                      isAiBlocked={isAiBlocked}
                      isRegenerating={isRegenerating}
                      blockedReason={actionBlockedReason}
                      reasonId={actionBlockedReasonId}
                      isLimitReached={isIllustrationLimitReached(chapter.revision)}
                      isAttachBusy={isPlacementBlocked}
                      attachPendingLabel={attachPendingLabel}
                      onAiEdit={() => void startBlockEdit(selectedIndexes)}
                      onManualEdit={() => {
                        if (actionRange !== null) startManualEdit(actionRange);
                      }}
                      onClearSelection={() => clearSelection(index)}
                      onAttach={(source, placement) => void attach(source, placement)}
                    />
                    {actionRange === null && (
                      <p className="text-sm break-keep text-muted-foreground">
                        떨어진 문단은 AI로만 함께 고칠 수 있어요. 직접 고치기와 그림 붙이기는 이어진 문단을 고르면 할 수 있어요.
                      </p>
                    )}
                  </>
                )}

                {isActionRowHere && activeMove === null && !isBlockMode && activeRange !== null && (
                  <ParagraphActionRow
                    actions={toParagraphActions({ isMoving: false, isIllustrationsOn })}
                    isAiBlocked={isAiBlocked}
                    isRegenerating={isRegenerating}
                    blockedReason={actionBlockedReason}
                    reasonId={actionBlockedReasonId}
                    isLimitReached={isIllustrationLimitReached(chapter.revision)}
                    isAttachBusy={isPlacementBlocked}
                    attachPendingLabel={attachPendingLabel}
                    onAiEdit={() => void startAiEdit(activeRange)}
                    onManualEdit={() => startManualEdit(activeRange)}
                    onClearSelection={() => clearSelection(activeRange.end)}
                    onAttach={(source, placement) => void attach(source, placement)}
                  />
                )}

                {previewsEndingAt(index).map((edit) => (
                  <AiEditPreview
                    key={edit.id}
                    edit={edit}
                    paragraphs={paragraphs}
                    isActing={aiEdit.actingEditId !== undefined}
                    onApply={() => void handlePreviewAction(() => aiEdit.apply(edit, chapter.ordinal))}
                    onDismiss={() => void handlePreviewAction(() => aiEdit.dismiss(edit, chapter.ordinal))}
                  />
                ))}
                {!isInEditRange && renderIllustrations(spots.after[index] ?? [], index, "after")}
                {patchLayout.bundlesAfter.get(index)?.map((unit) => (
                  <PatchBundleRow
                    key={unit.key}
                    unit={unit}
                    isActing={aiEdit.actingEditId !== undefined}
                    onApply={(target) => void handlePreviewAction(() => aiEdit.applyPatchUnit(target, chapter.ordinal))}
                    onDismiss={(target) =>
                      void handlePreviewAction(() => aiEdit.dismissPatches({ unit: target }, chapter.ordinal))
                    }
                    recheck={
                      isMultiBlockEditOn
                        ? {
                            isRechecking: aiEdit.actingEditId === toRecheckKey(unit),
                            onRecheck: (target) => void recheckBundle(target),
                          }
                        : undefined
                    }
                  />
                ))}
                {patchLayout.jobsAfter.get(index)?.map((job) => {
                  const remainingCount =
                    blockEdits
                      .find((edit) => edit.id === job.jobId)
                      ?.patches.filter((patch) => patch.state === "pending" || patch.state === "stale").length ?? 0;
                  return (
                    <PatchJobRow
                      key={job.jobId}
                      job={job}
                      remainingCount={remainingCount}
                      isActing={aiEdit.actingEditId !== undefined}
                      onDismissAll={() =>
                        void handlePreviewAction(() =>
                          aiEdit.dismissPatches({ jobId: job.jobId, remainingCount }, chapter.ordinal),
                        )
                      }
                    />
                  );
                })}
              </Fragment>
            );
          })}
        </div>
      </article>
    </div>
  );
}

/** 붙이기·바꾸기의 진행 문구. 올리는 중이면 "올리는 중…", 요청 중이면 `sendingLabel`, 아무것도 안 돌면 없다. */
function toPhaseLabel(request: ImageRequestPhase | undefined, sendingLabel: string): string | undefined {
  if (request === undefined) return undefined;
  return request.phase === "uploading" ? "올리는 중…" : sendingLabel;
}

/** 붙인 뒤 알림 줄 문장 — 몇째 문단 앞·뒤인지. 응답 판에서 그 문단을 찾지 못하면 자리를 말하지 않는다. */
function toAttachedMessage(blocks: readonly { id: string }[], request: AttachRequest): string {
  const index = blocks.findIndex((block) => block.id === request.target.anchorBlockId);
  if (index < 0) return "삽화를 붙였어요.";
  return `삽화를 ${index + 1}번째 문단 ${request.target.placement === "before" ? "앞에" : "뒤에"} 붙였어요.`;
}

type RetryAttachRowProps = {
  /** 실패한 붙이기의 문단이 지금 판에 남아 있는가. 없으면 다시 넣을 자리가 없어 문단을 다시 고르라고 말한다. */
  canRetry: boolean;
  isBlocked: boolean;
  /** 한 화의 삽화 상한에 닿았는가. 다시 넣어도 상한 409 로 끝나므로 다른 삽화를 뗄 때까지 막는다. */
  isLimitReached: boolean;
  isRetrying: boolean;
  onRetry: () => void;
};

/** 붙이기가 실패한 뒤 같은 그림으로 다시 넣는 줄. 올린 파일을 다시 올리지 않게 하려는 것이고, 다시 넣기는 그때의 지금 판을
 * 기준으로 간다. 그 문단이 지금 판에 없으면 버튼 대신 안내만 둔다. */
function RetryAttachRow({ canRetry, isBlocked, isLimitReached, isRetrying, onRetry }: RetryAttachRowProps) {
  const reasonId = useId();
  if (!canRetry) {
    return (
      <p className="text-sm break-keep text-muted-foreground">
        고른 문단이 바뀌어 같은 자리에 다시 넣을 수 없어요. 문단을 다시 골라 붙여 주세요.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={isBlocked || isLimitReached}
        aria-describedby={isLimitReached ? reasonId : undefined}
        className="w-fit aria-disabled:opacity-65"
        onClick={() => {
          if (isBlocked || isLimitReached) return;
          onRetry();
        }}
      >
        <RotateCcw aria-hidden />
        {isRetrying ? "붙이는 중…" : "같은 그림으로 다시 넣기"}
      </Button>
      {isLimitReached && (
        <p id={reasonId} className="text-sm break-keep text-muted-foreground">
          다른 삽화를 떼면 같은 그림으로 다시 넣을 수 있어요.
        </p>
      )}
    </div>
  );
}

function toAiBlockedReason(aiEdit: NovelAiEditFlow): string | undefined {
  if (aiEdit.isRunning) return "AI로 고치는 중이에요. 끝나면 다시 고칠 수 있어요.";
  if (aiEdit.isOtherJobRunning) return "화를 쓰는 중이에요. 끝나면 AI로 고칠 수 있어요.";
  return undefined;
}

type MoveTargetRowProps = {
  isBlocked: boolean;
  /** 다시 만드는 중이라 막혔으면 그 사유 문장의 id. 이 줄 안에 사유를 단다. */
  blockedReasonId: string | undefined;
  /** 진행 중인 옮기기 요청의 앞뒤. */
  pendingPlacement: IllustrationPlacement | undefined;
  onPlace: (placement: IllustrationPlacement) => void;
  onCancel: () => void;
};

/** 옮기는 중에 고른 문단 아래 서는 동작 줄 — 그 문단 앞에 놓기·뒤에 놓기·옮기기 취소. 고르기 동작 줄과 같은 자리·같은
 * 모양이라 "문단을 고르면 그 아래에서 할 일을 고른다"는 한 문법이다. */
function MoveTargetRow({ isBlocked, blockedReasonId, pendingPlacement, onPlace, onCancel }: MoveTargetRowProps) {
  return (
    <div className="flex flex-col gap-1.5 py-1">
      <div className="flex flex-wrap gap-2">
        {toParagraphActions({ isMoving: true, isIllustrationsOn: true }).map((action) => {
          if (action === "cancelMove") {
            return (
              <Button key={action} type="button" variant="ghost" size="sm" onClick={onCancel}>
                <X aria-hidden />
                옮기기 취소
              </Button>
            );
          }
          const placement: IllustrationPlacement = action === "placeBefore" ? "before" : "after";
          const Icon = placement === "before" ? ArrowUpToLine : ArrowDownToLine;
          return (
            <Button
              key={action}
              type="button"
              variant="outline"
              size="sm"
              aria-disabled={isBlocked}
              aria-describedby={blockedReasonId}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (isBlocked) return;
                onPlace(placement);
              }}
            >
              <Icon aria-hidden />
              {pendingPlacement === placement ? "옮기는 중…" : `이 문단 ${placement === "before" ? "앞" : "뒤"}에 놓기`}
            </Button>
          );
        })}
      </div>
      {blockedReasonId !== undefined && (
        <p id={blockedReasonId} className="text-sm break-keep text-muted-foreground">
          {CHAPTER_REGENERATING_MESSAGE}
        </p>
      )}
    </div>
  );
}

type ParagraphButtonProps = {
  ref: (element: HTMLButtonElement | null) => void;
  text: string;
  isSelected: boolean;
  /** 여러 문단 고르기에서 지금 고를 수 없는 까닭 문장의 id(다른 장면·상한). 있으면 `aria-disabled` 로 흐리고 그 문장을 가리킨다 —
   * 누르면 까닭을 알림 줄로 다시 말한다(버튼에서 포커스를 빼지 않는다). */
  blockedReasonId?: string;
  /** `extend` 는 Shift 를 누른 채 눌렀는가. */
  onSelect: (extend: boolean) => void;
};

/** 고치기 모드의 문단 하나. 읽기 모드의 `<p>` 와 같은 상자(안쪽 여백·음수 바깥 여백)라 모드를 바꿔도 글자가
 * 움직이지 않는다. Shift+Enter 는 브라우저가 클릭으로 바꿔 주지 않아 키 입력에서 직접 받는다.
 *
 * 두 표시는 각자 배경 대비 3:1 을 넘는 불투명 선이 진다(면 채움은 배경과 1.2:1 남짓이라 표시를 지지 못한다).
 * - **포커스**: 시스템의 보더 없는 컨트롤과 같은 레시피 — 불투명 1px `outline-ring` + 50% 링. 50% 링만으로는 페이지
 *   배경 대비 다크 2.58 / 라이트 2.55 로 미달이고, 불투명 윤곽은 7.18 / 6.70 이다. 보더를 쓰지 않는 것은 1px 가
 *   자리를 먹어 읽기 모드의 `<p>` 와 글자 위치가 어긋나서다.
 * - **고름**: 안쪽 1px `inset-ring-input`. 선의 바깥은 페이지 배경과 맞닿아 다크 3.54 / 라이트 3.64 로 통과한다
 *   (DESIGN.md 의 인풋 보더 대 `background` 실측과 같은 값). 안쪽은 고른 문단의 채움 `secondary` 와 맞닿아 다크 2.83 /
 *   라이트 2.97 로 3:1 에 못 미친다(DESIGN.md Colors 절에 적힌 미달 쌍). hover 해도 채움은 `secondary` 그대로라
 *   다른 쌍은 생기지 않는다. 바깥 경계 한 줄이 3:1 을 지므로 표시는 통과다.
 * 고름은 안쪽 그림자, 포커스는 바깥 링이라 Tailwind 4 가 한 `box-shadow` 에 함께 싣는다 — 고른 문단에 포커스가
 * 있어도(Enter 로 고른 직후가 그 상태다) 서로 덮지 않는다. */
function ParagraphButton({ ref, text, isSelected, blockedReasonId, onSelect }: ParagraphButtonProps) {
  const isBlocked = blockedReasonId !== undefined;
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={isSelected}
      aria-disabled={isBlocked || undefined}
      aria-describedby={blockedReasonId}
      className={cn(
        "-mx-2 cursor-pointer rounded-md px-2 py-1 text-left whitespace-pre-line motion-safe:transition-colors hover:bg-muted aria-pressed:bg-secondary aria-pressed:inset-ring-1 aria-pressed:inset-ring-input aria-pressed:hover:bg-secondary focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        isBlocked && "cursor-default text-muted-foreground hover:bg-transparent",
      )}
      onClick={(event: MouseEvent<HTMLButtonElement>) => onSelect(event.shiftKey)}
      onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
        if (event.key !== "Enter" || !event.shiftKey) return;
        event.preventDefault();
        onSelect(true);
      }}
    >
      {text}
    </button>
  );
}

type ManualEditorProps = {
  id: string;
  rangeLabel: string;
  draft: string;
  error: string | undefined;
  /** 시작한 뒤 이 장의 판이 바뀌었는가. */
  isStale: boolean;
  /** 이 장을 다시 만드는 중인가. 그동안은 저장을 막는다. */
  isRegenerating: boolean;
  /** 이 장에 적용하지 않은 AI 수정안이 있는가. 저장하면 서버가 그 수정안을 버린다. */
  hasPendingAiEdits: boolean;
  /** 고치는 범위의 블록에 지금 쓸 수 있는 여러 문단 수정안이 있는가. 그 문단을 고쳐 저장하면 그 수정안은 쓸 수 없게 된다(다른
   * 블록의 수정안은 그대로다). */
  hasPendingPatches: boolean;
  /** 고치는 범위 문단들의 앞·뒤 삽화 수. 입력칸이 그 자리를 대신해 그림이 보이지 않으므로 수와 결과를 한 줄로 말한다. */
  illustrationCount: number;
  isSaving: boolean;
  /** 삽화 요청이 도는 중인가. 같은 판을 기준으로 가므로 그동안 저장을 막는다. */
  isPlacing: boolean;
  onDraftChange: (draft: string) => void;
  onCancel: () => void;
  onSave: () => void;
};

/** 고른 문단 자리에 들어서는 입력칸. 문단 사이는 빈 줄 하나로 띄운다(저장할 때 빈 줄로 다시 나뉜다). 버튼은
 * `취소` 먼저이고, 저장 중에는 `aria-disabled` 로 막아 누른 버튼의 포커스를 지킨다.
 *
 * 이 장을 다시 만드는 동안은 저장을 막고 사유를 단다. 판이 바뀐 뒤에는 저장해도 충돌로 막힌다 — 쓴 글은 지우지 않고, 복사해 두고 최신 글에서 다시 고르라고 말한다.
 * 저장이 돈 낸 수정안을 버리게 되는 경우에는 저장 버튼 바로 위에서 미리 말한다. */
function ManualEditor({
  id,
  rangeLabel,
  draft,
  error,
  isStale,
  isRegenerating,
  hasPendingAiEdits,
  hasPendingPatches,
  illustrationCount,
  isSaving,
  isPlacing,
  onDraftChange,
  onCancel,
  onSave,
}: ManualEditorProps) {
  const isSaveBlocked = isSaving || isPlacing || isRegenerating;
  const saveDescribedBy = [
    isRegenerating && `${id}-regenerating`,
    hasPendingAiEdits && `${id}-pending`,
    hasPendingPatches && `${id}-patches`,
  ]
    .filter((part) => part !== false)
    .join(" ");

  return (
    <div className="flex flex-col gap-2 py-1">
      <Label htmlFor={id}>{rangeLabel} 직접 고치기</Label>
      <BuilderTextarea
        id={id}
        autoFocus
        value={draft}
        aria-invalid={error !== undefined}
        aria-describedby={`${id}-hint${error !== undefined ? ` ${id}-error` : ""}`}
        rows={8}
        className="leading-relaxed break-keep"
        onChange={(event) => onDraftChange(event.target.value)}
      />
      <p id={`${id}-hint`} className="text-xs break-keep text-muted-foreground">
        문단 사이는 빈 줄 하나로 띄워 주세요. 모두 지우면 고른 문단이 빠져요.
      </p>
      {error !== undefined && (
        <p id={`${id}-error`} role="alert" className="text-sm break-keep text-destructive-text">
          {error}
        </p>
      )}
      {illustrationCount > 0 && (
        <p className="text-sm break-keep text-muted-foreground">
          이 범위에 삽화 {illustrationCount}장이 있어요. 삽화가 붙은 문단을 지우면 그 삽화는 자리를 잃고 위치 확인 필요로
          옮겨져요.
        </p>
      )}
      {isStale && (
        <p className="text-sm break-keep text-muted-foreground">
          고치는 사이 이 장이 바뀌어 이대로는 저장할 수 없어요. 쓴 글을 복사해 두고 취소한 뒤, 최신 글에서 문단을 다시
          골라 주세요.
        </p>
      )}
      {isRegenerating && (
        <p id={`${id}-regenerating`} className="text-sm break-keep text-muted-foreground">
          {CHAPTER_REGENERATING_MESSAGE}
        </p>
      )}
      {hasPendingAiEdits && (
        <p id={`${id}-pending`} className="text-sm break-keep text-muted-foreground">
          저장하면 이 장에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.
        </p>
      )}
      {hasPendingPatches && (
        <p id={`${id}-patches`} className="text-sm break-keep text-muted-foreground">
          저장하면 고친 문단의 AI 수정안은 적용할 수 없게 되고, 쓴 클로버는 돌아오지 않아요.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          취소
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-disabled={isSaveBlocked}
          aria-describedby={saveDescribedBy || undefined}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isSaveBlocked) return;
            onSave();
          }}
        >
          {isSaving ? "저장 중…" : "저장"}
        </Button>
      </div>
    </div>
  );
}
