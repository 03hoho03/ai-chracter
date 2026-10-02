import { cn } from "@ai-character-chat/ui/lib/utils";
import { Copy, EyeOff, Plus } from "lucide-react";
import type { FocusEvent } from "react";

import { toMediaNameTag } from "@/entities/media-book";
import { findCell, type MediaBookCellValues, type MediaBookValues } from "@/features/build-story";

import { copyMediaTag } from "../lib/copyMediaTag";
import { useMediaBookThumbnails } from "../model/useMediaBookThumbnails";

export type MediaBookPosition = { personId: string; sceneId: string };

/**
 * 고정된 장면 이름 열(머리 행 모서리 칸 포함). 배경색 채움을 왼쪽으로 표 스크롤러 안쪽 여백(4px)만큼, 오른쪽으로 칸 사이
 * 간격(`border-spacing-2`, 8px)만큼 늘린다 — 셀 배경은 셀 상자만 덮어서, 표를 가로로 밀면 그 두 틈으로 밀려 들어간
 * 칸과 인물 이름 조각이 비치기 때문이다. 셀이 `truncate`(overflow hidden)라 의사 요소는 잘리므로 상자 밖으로 그려지는
 * box-shadow 를 쓴다. 번지기 없는 배경색 그대로라 깊이를 만드는 그림자가 아니라 면을 늘리는 채움이다.
 */
const STICKY_COLUMN_FILL =
  "sticky left-0 z-10 bg-background shadow-[-4px_0_var(--color-background),8px_0_var(--color-background)]";

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
 * 배치표 — 열은 인물, 줄은 장면이다. 인물은 대개 몇 명이고 장면은 늘어나므로 늘어나는 쪽을 세로(열 안 스크롤)로
 * 둔다. 인물이 많아 폭을 넘으면 표만 가로로 밀린다(장면 이름 열은 고정). 칸은 고정 크기이고 그림은 원래 비율 그대로
 * 칸 안에 맞춘다(`object-contain`) — 칸 크기가 그림과 무관해 그림이 도착해도 표가 움직이지 않는다.
 */
export function MediaBookGrid({ mediaBook, selected, onSelect, panelId }: MediaBookGridProps) {
  return (
    // `overflow-x-auto` 는 포커스 링을 네 방향 모두 자른다 — 링 두께만큼 안팎으로 상쇄한다.
    // `scroll-pl-28` 은 칸이나 칸 모서리 버튼을 표 안으로 들일 때(다음 미완성 칸, 배치표로 돌아가기, 키보드 포커스)
    // 왼쪽 기준선을 고정된 장면 이름 열(안쪽 여백 4px + 최대 96px + 칸 사이 간격 8px) 너머로 옮겨, 표를 가로로 민
    // 상태에서도 들인 것이 그 열 밑에 숨지 않게 한다.
    <div className="-m-1 overflow-x-auto scroll-pl-28 p-1">
      <table className="border-separate border-spacing-2 text-left">
        <caption className="sr-only">미디어 북 배치표 — 열은 인물, 줄은 장면</caption>
        <thead>
          <tr>
            <td className={STICKY_COLUMN_FILL} />
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
                className={cn(STICKY_COLUMN_FILL, "max-w-24 truncate pr-1 text-xs font-medium text-foreground")}
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

  function handleFocus(event: FocusEvent<HTMLDivElement>) {
    // 표를 가로로 민 채 키보드로 들어온 칸·버튼이 고정된 장면 이름 열 밑에 걸쳐 있어도, 브라우저는 일부가 보이면
    // 스크롤하지 않는다. 가까운 쪽으로 직접 들인다(표 스크롤러의 scroll-padding 이 장면 열 너머에 세운다).
    // 마우스로 누른 칸은 포커스 링이 없어 그대로 둔다.
    if (event.target.matches(":focus-visible")) event.target.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function handleCopy() {
    // 모서리를 눌러도 그 칸을 함께 고른다 — 아니면 선택이 직전 칸에 남아, 다음에 고른 이미지가 엉뚱한 칸에 들어간다.
    onSelect("copy");
    void copyMediaTag(tag);
  }

  return (
    // 포커스 링이 있는 동안은 고정된 장면 이름 열보다 위에 그린다 — 그 열의 배경 채움이 칸 사이 간격까지 덮어서,
    // 첫 인물 열 칸의 링 왼쪽이 그 밑에 깔리기 때문이다.
    <div className="relative size-20 has-[:focus-visible]:z-20" onFocus={handleFocus}>
      <button
        type="button"
        aria-pressed={isSelected}
        aria-controls={isSelected ? panelId : undefined}
        aria-label={`${personName} / ${sceneName} — ${describeCell(cell)}`}
        data-media-book-cell={cellKey}
        onClick={(event) => onSelect(event.detail === 0 ? "keyboard" : "pointer")}
        className={cn(
          // 칸을 화면에 들일 때(다음 미완성 칸, 배치표로 돌아가기) 위에 남기는 여유 — 배치표 묶음 본문 안의 숨 쉴 자리.
          // 왼쪽 여유는 표 스크롤러의 scroll-padding 이 맡는다(칸 모서리 버튼도 같은 기준선을 쓰게).
          "scroll-mt-2",
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
