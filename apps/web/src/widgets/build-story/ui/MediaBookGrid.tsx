import { cn } from "@ai-character-chat/ui/lib/utils";
import { Copy, EyeOff, Plus } from "lucide-react";

import { toMediaNameTag } from "@/entities/media-book";
import { findCell, type MediaBookCellValues, type MediaBookValues } from "@/features/build-story";

import { copyMediaTag } from "../lib/copyMediaTag";
import { useMediaBookThumbnails } from "../model/useMediaBookThumbnails";

export type MediaBookPosition = { personId: string; sceneId: string };

/**
 * 칸을 어떻게 골랐는가 — 탭이 스크롤·포커스·알림을 이걸로 가른다. `keyboard` 는 Enter·Space(클릭 이벤트의
 * `detail` 이 0), `copy` 는 칸 모서리의 표기 복사 버튼이다.
 */
export type MediaBookSelectMethod = "pointer" | "keyboard" | "copy";

type MediaBookGridProps = {
  mediaBook: MediaBookValues;
  selected: MediaBookPosition | undefined;
  onSelect: (position: MediaBookPosition, method: MediaBookSelectMethod) => void;
  panelId: string;
};

/**
 * 배치표 — 열은 인물, 줄은 장면이다. 인물은 대개 몇 명이고 장면은 늘어나므로 늘어나는 쪽을 세로(페이지 스크롤)로
 * 둔다. 인물이 많아 폭을 넘으면 표만 가로로 밀린다(장면 이름 열은 고정). 칸은 고정 크기이고 그림은 원래 비율 그대로
 * 칸 안에 맞춘다(`object-contain`) — 칸 크기가 그림과 무관해 그림이 도착해도 표가 움직이지 않는다.
 */
export function MediaBookGrid({ mediaBook, selected, onSelect, panelId }: MediaBookGridProps) {
  return (
    // `overflow-x-auto` 는 포커스 링을 네 방향 모두 자른다 — 링 두께만큼 안팎으로 상쇄한다.
    <div className="-m-1 overflow-x-auto p-1">
      <table className="border-separate border-spacing-2 text-left">
        <caption className="sr-only">미디어 북 배치표 — 열은 인물, 줄은 장면</caption>
        <thead>
          <tr>
            <td className="sticky left-0 z-10 bg-background" />
            {mediaBook.people.map((person) => (
              <th
                key={person.id}
                scope="col"
                className="w-20 max-w-20 truncate px-0.5 pb-1 text-xs font-medium text-foreground"
                title={person.name}
              >
                {person.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {mediaBook.scenes.map((scene) => (
            <tr key={scene.id}>
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-24 truncate bg-background pr-1 text-xs font-medium text-foreground"
                title={scene.name}
              >
                {scene.name}
              </th>
              {mediaBook.people.map((person) => (
                <td key={person.id} className="p-0">
                  <GridCell
                    personName={person.name}
                    sceneName={scene.name}
                    cell={findCell(mediaBook, person.id, scene.id)}
                    isSelected={selected?.personId === person.id && selected.sceneId === scene.id}
                    panelId={panelId}
                    onSelect={(method) => onSelect({ personId: person.id, sceneId: scene.id }, method)}
                    cellKey={toCellKey({ personId: person.id, sceneId: scene.id })}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type GridCellProps = {
  personName: string;
  sceneName: string;
  cell: MediaBookCellValues | undefined;
  isSelected: boolean;
  panelId: string;
  onSelect: (method: MediaBookSelectMethod) => void;
  cellKey: string;
};

function GridCell({ personName, sceneName, cell, isSelected, panelId, onSelect, cellKey }: GridCellProps) {
  const thumbnails = useMediaBookThumbnails();
  const imageUrl = cell ? thumbnails.resolveUrl(cell.imageAssetId, cell.imageUrl) : undefined;
  const tag = toMediaNameTag(personName, sceneName);

  function handleCopy() {
    // 모서리를 눌러도 그 칸을 함께 고른다 — 아니면 선택이 직전 칸에 남아, 다음에 고른 이미지가 엉뚱한 칸에 들어간다.
    onSelect("copy");
    void copyMediaTag(tag);
  }

  return (
    <div className="relative size-20">
      <button
        type="button"
        aria-pressed={isSelected}
        aria-controls={isSelected ? panelId : undefined}
        aria-label={`${personName} / ${sceneName} — ${describeCell(cell)}`}
        data-media-book-cell={cellKey}
        onClick={(event) => onSelect(event.detail === 0 ? "keyboard" : "pointer")}
        className={cn(
          // 고른 뒤 스크롤이 이 칸을 상단바 밑에 숨기지 않게 위쪽 여유를 둔다(좁은 화면은 페이지가, 넓은 화면은 상단바
          // 아래에서 시작하는 폼 열이 스크롤된다).
          "scroll-mt-16 lg:scroll-mt-4",
          // 포커스는 하우스 레시피 — 3:1 은 불투명 보더가 지고, 반투명 링은 어디인지 보여 준다.
          "flex size-full items-center justify-center overflow-hidden rounded-lg focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
          cell
            ? "border border-foreground/10 bg-muted"
            : "border border-dashed border-input text-muted-foreground hover:bg-muted hover:text-foreground",
          // 고른 칸은 채움이 아니라 불투명 전경색 테두리로 가린다 — 썸네일이 칸을 덮으므로 채움은 보이지 않는다.
          isSelected && "border-2 border-foreground",
        )}
      >
        {!cell && <Plus aria-hidden className="size-5" />}
        {!!imageUrl && <img src={imageUrl} alt="" loading="lazy" decoding="async" className="size-full object-contain" />}
      </button>
      {cell?.excludeFromChat && (
        // 그림 위에 얹는 표식이라 테마와 무관한 스크림 쌍을 쓴다.
        <span className="pointer-events-none absolute top-1 left-1 inline-flex size-5 items-center justify-center rounded-md bg-scrim/70 text-scrim-foreground">
          <EyeOff aria-hidden className="size-3" />
        </span>
      )}
      {cell && (
        <button
          type="button"
          aria-label={`${tag} 표기 복사`}
          onClick={handleCopy}
          className="absolute right-1 bottom-1 inline-flex size-6 items-center justify-center rounded-md border border-transparent bg-scrim/70 text-scrim-foreground hover:bg-scrim focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <Copy aria-hidden className="size-3.5" />
        </button>
      )}
    </div>
  );
}

/** 칸 버튼 접근 이름의 상태 부분. 표에는 상황 설명 유무 표식이 없어 이름이 그 정보를 싣는다. */
function describeCell(cell: MediaBookCellValues | undefined): string {
  if (!cell) return "비어 있음";
  const parts = ["이미지 있음"];
  if (cell.situationDescription.trim() === "") parts.push("상황 설명 없음");
  if (cell.excludeFromChat) parts.push("대화 중 띄우지 않음");
  return parts.join(", ");
}

/** 표의 칸 버튼을 찾는 표식 값. uuid 에는 `|` 가 없어 자리끼리 겹치지 않는다. */
export function toCellKey(position: MediaBookPosition): string {
  return `${position.personId}|${position.sceneId}`;
}

/** 표의 그 칸 버튼으로 포커스를 옮긴다(상세를 닫거나 비운 뒤). */
export function focusGridCell(position: MediaBookPosition) {
  document.querySelector<HTMLButtonElement>(`[data-media-book-cell="${toCellKey(position)}"]`)?.focus();
}
