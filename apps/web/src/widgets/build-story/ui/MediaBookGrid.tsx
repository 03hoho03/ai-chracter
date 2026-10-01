import { cn } from "@ai-character-chat/ui/lib/utils";
import { Copy, EyeOff, Plus } from "lucide-react";
import { toast } from "sonner";

import { findCell, toMediaTag, type MediaBookCellValues, type MediaBookValues } from "@/features/build-story";

import { useMediaBookThumbnails } from "./MediaBookThumbnailsProvider";

export type MediaBookPosition = { personId: string; sceneId: string };

/** 표의 칸 버튼을 찾는 표식 값. uuid 에는 `|` 가 없어 자리끼리 겹치지 않는다. */
export function toCellKey(position: MediaBookPosition): string {
  return `${position.personId}|${position.sceneId}`;
}

/** 표의 그 칸 버튼으로 포커스를 옮긴다(상세를 닫거나 비운 뒤). */
export function focusGridCell(position: MediaBookPosition) {
  document.querySelector<HTMLButtonElement>(`[data-media-book-cell="${toCellKey(position)}"]`)?.focus();
}

type MediaBookGridProps = {
  mediaBook: MediaBookValues;
  selected: MediaBookPosition | undefined;
  /** `viaKeyboard` — Enter·Space 로 눌렀는가(클릭 이벤트의 `detail` 이 0). */
  onSelect: (position: MediaBookPosition, viaKeyboard: boolean) => void;
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
                    onSelect={(viaKeyboard) => onSelect({ personId: person.id, sceneId: scene.id }, viaKeyboard)}
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
  onSelect: (viaKeyboard: boolean) => void;
  cellKey: string;
};

function GridCell({ personName, sceneName, cell, isSelected, panelId, onSelect, cellKey }: GridCellProps) {
  const thumbnails = useMediaBookThumbnails();
  const imageUrl = cell ? thumbnails.resolveUrl(cell.imageAssetId, cell.imageUrl) : undefined;
  const tag = toMediaTag(personName, sceneName);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(tag);
      toast.success("이미지 표기를 복사했어요. 시작상황·프롤로그·에필로그·등록 설명에 붙여 넣으면 그 자리에 그림이 보여요.");
    } catch {
      toast.error(`복사하지 못했어요. 직접 입력해 주세요: ${tag}`);
    }
  }

  return (
    <div className="relative size-20">
      <button
        type="button"
        aria-pressed={isSelected}
        aria-controls={isSelected ? panelId : undefined}
        aria-label={`${personName} / ${sceneName} — ${cell ? "이미지 있음" : "비어 있음"}${cell?.excludeFromChat ? ", 대화 중 띄우지 않음" : ""}`}
        data-media-book-cell={cellKey}
        onClick={(event) => onSelect(event.detail === 0)}
        className={cn(
          "flex size-full items-center justify-center overflow-hidden rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          cell
            ? "border border-foreground/10 bg-muted"
            : "border border-dashed border-input text-muted-foreground hover:bg-muted hover:text-foreground",
          // 고른 칸은 채움이 아니라 불투명 전경색 테두리로 가린다 — 썸네일이 칸을 덮으므로 채움은 보이지 않는다.
          isSelected && "border-2 border-foreground",
        )}
      >
        {!cell && <Plus aria-hidden className="size-5" />}
        {imageUrl && <img src={imageUrl} alt="" loading="lazy" decoding="async" className="size-full object-contain" />}
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
          onClick={() => void handleCopy()}
          className="absolute right-1 bottom-1 inline-flex size-6 items-center justify-center rounded-md bg-scrim/70 text-scrim-foreground hover:bg-scrim focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Copy aria-hidden className="size-3.5" />
        </button>
      )}
    </div>
  );
}
