import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { useEffect, useRef } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { focusNeighborToggle, itemOpenKey, useBuilderSelection, useBuilderUiState } from "@/features/build-common";
import {
  FieldLabelText,
  MAX_SITUATION_NOTES,
  SELECTED_STARTING_SETUP,
  type SituationNoteValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { SituationNoteCard } from "./SituationNoteCard";
import { StartingSetupPicker } from "./StartingSetupPicker";

const SITUATION_NOTE_LIST: StoryCollapsibleList = "situationNote";
const ADD_BUTTON_ID = "situation-note-add";
const ADD_REASON_ID = "situation-note-add-reason";
const NO_STATS_REASON = "상황 노트는 스탯 값으로 조건을 걸어요. 이 시작설정에는 아직 스탯이 없어요.";

/**
 * 상황 노트 탭. 스탯·엔딩 탭처럼 시작설정마다 독립 목록이라 먼저 시작설정을 고른다(고른 시작설정은 두 탭과 함께 셸의 화면
 * 상태에서 읽고 쓴다). 하나도 없어도 발행할 수 있다.
 */
export function SituationNoteTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control } = form;
  const startingSetups = useWatch({ control, name: "startingSetups" });
  const [selectedSetupId, setSelectedSetupId] = useBuilderSelection(SELECTED_STARTING_SETUP);

  if (startingSetups.length === 0) {
    // 다른 탭 본문과 같은 `py-6` 루트로 감싸야 탭 목록과의 간격이 탭마다 같다.
    return (
      <div className="py-6">
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-20 text-center">
          <p className="text-sm break-keep text-muted-foreground">먼저 시작설정 탭에서 시작설정을 추가해주세요.</p>
        </div>
      </div>
    );
  }

  // 기억해 둔 시작설정이 지워졌거나 아직 고른 적이 없으면 첫 시작설정을 보인다.
  const selectedIndex = startingSetups.findIndex((setup) => setup.id === selectedSetupId);
  const effectiveIndex = selectedIndex !== -1 ? selectedIndex : 0;
  const effectiveSetup = startingSetups[effectiveIndex];

  return (
    <div className="flex flex-col gap-6 py-6">
      <StartingSetupPicker
        startingSetups={startingSetups}
        selectedIndex={effectiveIndex}
        onSelect={setSelectedSetupId}
        itemNoun="상황 노트"
        note="하나도 없어도 발행할 수 있어요."
      />

      {effectiveSetup && <SituationNoteSection key={effectiveSetup.id} startingSetupIndex={effectiveIndex} />}
    </div>
  );
}

/**
 * 고른 시작설정 하나의 상황 노트 목록. 노트 추가·삭제는 목록을 통째로 바꿔 쓴다(`setValue`) — 카드는 폼 값의 노트 id 를 key 로
 * 써서 목록이 바뀌어도 다시 마운트되지 않는다. 순서 바꾸기는 두지 않는다: 조건에 맞는 노트는 개수와 상관없이 모두 실려
 * 순서가 결과를 바꾸지 않는다.
 */
function SituationNoteSection({ startingSetupIndex }: { startingSetupIndex: number }) {
  const form = useFormContext<StoryBuilderFormValues>();
  const uiState = useBuilderUiState();

  const {
    control,
    getValues,
    setValue,
    setFocus,
    formState: { errors },
  } = form;
  const notesPath = `startingSetups.${startingSetupIndex}.situationNotes` as const;
  const notes = useWatch({ control, name: notesPath });
  const stats = useWatch({ control, name: `startingSetups.${startingSetupIndex}.stats` });
  // 새 노트의 이름 칸. 목록을 바꿔 쓴 렌더가 끝난 뒤에야 그 칸이 등록되므로 effect 에서 포커스한다.
  const pendingFocusIndexRef = useRef<number | undefined>(undefined);
  const isFull = notes.length >= MAX_SITUATION_NOTES;
  const hasNoStats = stats.length === 0;
  // 서버 거절이 노트 하나를 짚지 못하면 목록 자리에 오류가 걸린다 — 담기는 자리는 `.message` 와 `.root.message` 로 갈릴 수
  // 있어(키워드북 탭의 같은 자리 주석 참고) 둘 다 읽는다.
  const notesErrors = errors.startingSetups?.[startingSetupIndex]?.situationNotes;
  const listErrorMessage = notesErrors?.message ?? notesErrors?.root?.message;

  useEffect(() => {
    const index = pendingFocusIndexRef.current;
    if (index === undefined) return;
    pendingFocusIndexRef.current = undefined;
    setFocus(`${notesPath}.${index}.name`);
  }, [notes.length, notesPath, setFocus]);

  function writeNotes(next: SituationNoteValues[]) {
    setValue(notesPath, next, { shouldDirty: true });
  }

  function handleAdd() {
    // 11번째 노트·스탯 없는 조건은 서버가 저장을 거절하거나 쓸 수 없는 노트라 폼에 들어가지 않게 한다. 버튼의 잠금 표시는
    // 포인터만 막으므로 키보드로 눌러도 여기서 막는다.
    if (isFull || hasNoStats) return;
    const id = crypto.randomUUID();
    // 새 노트를 열림으로 기록하는 일은 목록을 바꾸기 전에 한다 — 같은 커밋에 본문이 보여야 포커스가 숨은 칸에 헛걸리지 않는다.
    uiState.open([itemOpenKey(SITUATION_NOTE_LIST, id)]);
    pendingFocusIndexRef.current = notes.length;
    writeNotes([...getValues(notesPath), { id, name: "", content: "", conditionRules: [] }]);
  }

  function handleRemove(index: number) {
    // 지운 자리의 다음 노트(없으면 앞 노트, 그것도 없으면 추가 버튼)의 머리 줄로 포커스를 먼저 옮긴다 — 지운 뒤로 미루면 누른
    // 삭제 버튼이 사라지며 포커스가 body 로 떨어진다.
    const current = getValues(notesPath);
    focusNeighborToggle(
      current.map((note) => itemOpenKey(SITUATION_NOTE_LIST, note.id)),
      index,
      document.getElementById(ADD_BUTTON_ID),
    );
    writeNotes(current.filter((_, noteIndex) => noteIndex !== index));
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <Label><FieldLabelText field="startingSetups.*.situationNotes" /></Label>
          <p className="text-xs tabular-nums text-muted-foreground">
            노트 {notes.length} / {MAX_SITUATION_NOTES}
          </p>
        </div>
        <p className="text-sm break-keep text-muted-foreground">
          스탯이 조건에 맞는 턴마다 그 노트의 글을 이야기를 쓰는 AI에게 ‘지금 이야기 속 사실’로 전해요. 조건에 맞는 노트는
          모두 실려요.
        </p>
        <p className="text-sm break-keep text-muted-foreground">
          조건은 사용자가 메시지를 보낸 순간의 게이지 값으로 따져요 — 이번 턴 판정이 반영된 뒤 값을 보는 엔딩 규칙보다 한 턴
          앞이에요.
        </p>
        <details className="group rounded-xl border border-border px-4 py-3">
          <summary className="cursor-pointer rounded-md text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            동작과 작성 요령
          </summary>
          <ul className="mt-3 flex list-disc flex-col gap-1.5 pl-5 text-sm break-keep text-muted-foreground marker:text-muted-foreground">
            <li>
              ‘~하게 써라’ 같은 지시 대신 ‘오늘은 상영회 당일이다’처럼 지금 사실인 상황으로 적어 주세요.
            </li>
            <li>
              AI는 게이지 숫자를 보지 못하고 노트의 글만 받아요. 값이 바뀌어도 맞는 표현(‘일주일도 남지 않았다’)으로
              적고, ‘3일 남았다’처럼 숫자를 박지 마세요.
            </li>
            <li>
              조건이 겹치면 두 노트가 함께 실려요. 서로 어긋나는 사실이 함께 실리지 않게 구간을 나눠 주세요(예: ‘&lt;=
              0’과 ‘&lt;= 7’은 0일 때 둘 다 맞아요).
            </li>
            <li>이름은 목록에서만 보이고 AI에게 보내지 않아요.</li>
            <li>조건 없이 늘 실을 내용은 스토리 설정에, 단어가 나올 때 실을 내용은 키워드북에 적어 주세요.</li>
            <li>미리보기에서 대화하던 중에 노트를 고쳤다면 미리보기 초기화를 눌러야 반영돼요.</li>
          </ul>
        </details>
        {!!listErrorMessage && (
          <p role="alert" className="text-xs text-destructive-text">
            {listErrorMessage}
          </p>
        )}
      </div>

      {notes.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border px-4 py-10 text-center">
          {hasNoStats ? (
            <>
              <p id={ADD_REASON_ID} className="text-sm break-keep text-muted-foreground">
                {NO_STATS_REASON}
              </p>
              <p className="text-sm break-keep text-muted-foreground">스탯 탭에서 스탯을 먼저 추가해주세요.</p>
            </>
          ) : (
            <>
              <p className="text-sm break-keep text-muted-foreground">아직 상황 노트가 없어요.</p>
              <p className="text-sm break-keep text-muted-foreground">
                예: ‘상영회까지 &lt;= 0’이면 ‘오늘은 가을 상영회 당일이다.’
              </p>
            </>
          )}
        </div>
      ) : (
        <ol className="flex flex-col gap-4" aria-label="상황 노트 목록">
          {notes.map((note, index) => (
            <li key={note.id}>
              <SituationNoteCard
                startingSetupIndex={startingSetupIndex}
                noteIndex={index}
                note={note}
                stats={stats}
                onRemove={() => handleRemove(index)}
              />
            </li>
          ))}
        </ol>
      )}

      <div className="flex flex-col gap-1.5">
        {/* 상한·스탯 없음에서도 버튼을 남기고 `aria-disabled` 로 잠근다 — 지우면 왜 더 못 만드는지가 사라지고, `disabled` 는
            포커스를 body 로 떨어뜨린다. 실제 차단은 handleAdd 다. 스탯이 없고 노트도 없으면 사유는 위 빈 상태 문장이 맡는다. */}
        <Button
          id={ADD_BUTTON_ID}
          type="button"
          variant="secondary"
          className="w-fit aria-disabled:pointer-events-none aria-disabled:opacity-65"
          aria-disabled={isFull || hasNoStats || undefined}
          aria-describedby={isFull || hasNoStats ? ADD_REASON_ID : undefined}
          onClick={handleAdd}
        >
          노트 추가
        </Button>
        {(isFull || (hasNoStats && notes.length > 0)) && (
          <p id={ADD_REASON_ID} className="text-xs break-keep text-muted-foreground">
            {isFull
              ? `노트는 시작설정마다 ${MAX_SITUATION_NOTES}개까지예요. 더 넣으려면 쓰지 않는 노트를 지워 주세요.`
              : NO_STATS_REASON}
          </p>
        )}
      </div>
    </div>
  );
}
