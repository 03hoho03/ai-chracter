import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { ArrowDown, ArrowUp, Ellipsis, History, Pencil, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";

import type { SceneDraft, SceneText } from "../model/episodeScenes";
import { toBasisLabel, toEpisodeTurns, type TurnIndex } from "../model/outlineEdits";

import { BasisToggle, MenuAction, TurnLine, type OutlineTurnsStatus } from "./OutlineEpisodeItem";
import { SceneForm } from "./SceneForm";

type SceneItemProps = {
  scene: SceneDraft;
  /** 장면 차례(1부터). 원고는 이 차례대로 장면을 쓴다. */
  number: number;
  turnIndex: TurnIndex | undefined;
  turnsStatus: OutlineTurnsStatus;
  /** 이 장면을 지금 고칠 수 있는가(낡음·원고 있음·방 없음·장면 구성안 작업 중이면 아니다). 아니면 고치기·메뉴가 없다. */
  canEdit: boolean;
  isEditing: boolean;
  moveBlockedReasons: { up: string | undefined; down: string | undefined };
  removeBlockedReason: string | undefined;
  titleMaxLength: number;
  onEdit: () => void;
  onApply: (text: SceneText) => void;
  onCancelEdit: () => void;
  onMove: (delta: -1 | 1) => void;
  onToggleFlashback: () => void;
  onRemove: () => void;
};

/**
 * 장면 구성안의 장면 하나 — 장면 차례·제목·회상 표시, 내용, 목적, 등장인물, 근거 대화. 근거는 고치지 않는다(전체 구성안에서 화를
 * 나누거나 합쳐서만 바뀐다). 근거 대화는 접혀 있다가 "근거 n~m턴"을 누르면 턴마다 두 줄 발췌로 펼친다.
 *
 * 구조 바꾸기(차례·회상 표시·빼기)는 "⋯" 메뉴에 모은다. 못 하는 항목은 메뉴에 남겨 두고 `aria-disabled` + 바로 아래 이유 줄을 단다.
 */
export function SceneItem({
  scene,
  number,
  turnIndex,
  turnsStatus,
  canEdit,
  isEditing,
  moveBlockedReasons,
  removeBlockedReason,
  titleMaxLength,
  onEdit,
  onApply,
  onCancelEdit,
  onMove,
  onToggleFlashback,
  onRemove,
}: SceneItemProps) {
  const headingId = useId();
  const basisListId = useId();
  const [isBasisOpen, setIsBasisOpen] = useState(false);
  const label = `장면 ${number}`;
  const basisLabel = turnIndex === undefined ? undefined : toBasisLabel(turnIndex, scene.basis);
  const turns = turnIndex === undefined ? undefined : toEpisodeTurns(turnIndex, scene.basis);

  return (
    <li
      aria-labelledby={headingId}
      data-plan-scene={scene.localId}
      className="flex flex-col gap-2.5 rounded-xl border border-border px-4 py-3"
    >
      <div className="flex items-start gap-2">
        <h5 id={headingId} className="min-w-0 flex-1 text-sm font-semibold break-keep text-foreground">
          <span className="text-muted-foreground tabular-nums">{label}</span> ·{" "}
          {scene.title.trim() === "" ? "제목 없음" : scene.title}
        </h5>
        {scene.flashback && (
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            회상
          </span>
        )}
        {canEdit && !isEditing && (
          <div className="-my-1 flex shrink-0 items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`${label} 고치기`}
              data-scene-edit={scene.localId}
              onClick={onEdit}
            >
              <Pencil aria-hidden />
            </Button>
            <SceneMenu
              label={label}
              localId={scene.localId}
              isFlashback={scene.flashback}
              moveBlockedReasons={moveBlockedReasons}
              removeBlockedReason={removeBlockedReason}
              onMove={onMove}
              onToggleFlashback={onToggleFlashback}
              onRemove={onRemove}
            />
          </div>
        )}
      </div>

      {isEditing ? (
        <SceneForm
          label={label}
          initial={{ title: scene.title, summary: scene.summary, purpose: scene.purpose }}
          titleMaxLength={titleMaxLength}
          onApply={onApply}
          onCancel={onCancelEdit}
        />
      ) : (
        <>
          <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{scene.summary}</p>
          {scene.purpose.trim() !== "" && (
            <p className="text-sm whitespace-pre-line break-keep text-muted-foreground">
              <span className="font-medium text-foreground">목적</span> · {scene.purpose}
            </p>
          )}
          {scene.characters.length > 0 && (
            <p className="text-sm break-keep text-muted-foreground">
              <span className="font-medium text-foreground">등장인물</span> · {scene.characters.join(", ")}
            </p>
          )}
        </>
      )}

      <div className="flex flex-col gap-2">
        <BasisToggle
          status={turnsStatus}
          basisLabel={basisLabel}
          isOpen={isBasisOpen}
          controlsId={basisListId}
          onToggle={() => setIsBasisOpen((open) => !open)}
        />
        {isBasisOpen && turns !== undefined && (
          <ol id={basisListId} aria-label={`${label} 근거 대화`} className="flex flex-col gap-1">
            {turns.map((turn) => (
              <li key={turn.key}>
                <TurnLine number={turn.number} excerpt={turn.excerpt} />
              </li>
            ))}
          </ol>
        )}
      </div>
    </li>
  );
}

type SceneMenuProps = {
  label: string;
  localId: string;
  isFlashback: boolean;
  moveBlockedReasons: { up: string | undefined; down: string | undefined };
  removeBlockedReason: string | undefined;
  onMove: (delta: -1 | 1) => void;
  onToggleFlashback: () => void;
  onRemove: () => void;
};

function SceneMenu({
  label,
  localId,
  isFlashback,
  moveBlockedReasons,
  removeBlockedReason,
  onMove,
  onToggleFlashback,
  onRemove,
}: SceneMenuProps) {
  // 빼기는 포커스를 이웃 장면의 메뉴로 옮긴다. 메뉴가 열린 동안에는 포커스가 메뉴 안에 갇혀 옮길 수 없고, 닫히면 트리거로 되돌아가 그
  // 이동을 덮는다 — 그래서 메뉴가 닫힌 순간 트리거 되돌리기를 막고 실행한다(전체 구성안 화 메뉴와 같은 처리).
  const afterCloseRef = useRef<(() => void) | undefined>(undefined);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={`${label} 바꾸기`} data-scene-menu={localId}>
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-auto"
        onCloseAutoFocus={(event) => {
          const action = afterCloseRef.current;
          if (action === undefined) return;
          afterCloseRef.current = undefined;
          event.preventDefault();
          action();
        }}
      >
        <MenuAction icon={<ArrowUp aria-hidden />} blockedReason={moveBlockedReasons.up} onSelect={() => onMove(-1)}>
          위로 옮기기
        </MenuAction>
        <MenuAction icon={<ArrowDown aria-hidden />} blockedReason={moveBlockedReasons.down} onSelect={() => onMove(1)}>
          아래로 옮기기
        </MenuAction>
        <DropdownMenuSeparator />
        <MenuAction icon={<History aria-hidden />} blockedReason={undefined} onSelect={onToggleFlashback}>
          {isFlashback ? "회상 표시 빼기" : "회상 장면으로 표시"}
        </MenuAction>
        <DropdownMenuSeparator />
        <MenuAction
          icon={<Trash2 aria-hidden />}
          variant="destructive"
          blockedReason={removeBlockedReason}
          onSelect={() => {
            afterCloseRef.current = onRemove;
          }}
        >
          장면 빼기
        </MenuAction>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
