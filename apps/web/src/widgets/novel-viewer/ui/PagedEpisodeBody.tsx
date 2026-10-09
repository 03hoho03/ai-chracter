import { useEffect, useImperativeHandle, useRef, type Ref, type RefObject } from "react";

import type { NovelChapterSummary, NovelDetailResponse } from "@/entities/novel";

import type { PageFit } from "../lib/pageFit";
import { PAGE_FORMAT_HEIGHT_PX, PAGE_FORMAT_PADDING_PX, PAGE_FORMAT_WIDTH_PX, type PageTypography } from "../lib/pageFormat";
import { useIsFinePointer } from "../lib/useIsFinePointer";
import { usePagedReader, type PagedPosition, type PagedReaderHandle } from "../model/usePagedReader";
import { usePageInput } from "../model/usePageInput";
import type { ReadingPositionSession } from "../model/useReadingPosition";
import { EpisodeEnd } from "./EpisodeEnd";
import { EpisodeHeader } from "./EpisodeHeader";
import { PageTurnButton } from "./PageTurnButton";

/** 넘김 버튼과 판형 사이 간격, 버튼 크기(px). 배율 계산이 비워 둔 거터(바깥 8 + 버튼 40 + 안쪽 8) 안에 놓인다. */
const PAGE_BUTTON_GAP_PX = 8;
const PAGE_BUTTON_SIZE_PX = 40;
/** 화 머리와 본문 사이(판형 px). */
const HEADER_GAP_PX = 32;

type PagedEpisodeBodyProps = {
  ref?: Ref<PagedReaderHandle>;
  novel: NovelDetailResponse;
  summary: NovelChapterSummary;
  episodeLabel: string;
  paragraphs: readonly string[];
  next: NovelChapterSummary | undefined;
  /** 창에 판형을 맞춘 배치 — 배율·한 장/펼침·화면 위치. */
  fit: PageFit;
  /** 보기 설정(글자 크기·줄 간격)에서 나온 판형 안 조판값(px). */
  typography: PageTypography;
  readingPosition: ReadingPositionSession;
  onPositionChange: (position: PagedPosition) => void;
  isSettingsOpen: boolean;
  settingsPanelRef: RefObject<HTMLElement | null>;
  /** 본문 가운데 탭 — 보기 설정이 열려 있으면 그것만 닫고, 아니면 바를 여닫는다. */
  onBodyTap: () => void;
  onOpenToc: (opener: HTMLElement) => void;
};

/**
 * 쪽을 좌우로 넘겨 읽는 화 본문(페이지 모드). 본문을 고정 판형(논리 360×540px, 펼침이면 두 장)에 조판하고 판형
 * 묶음을 `transform: scale` 로 화면에 맞춘다 — 배율은 위·아래 바 자리를 늘 비운 영역에서 정해져, 바를 여닫아도
 * 판형이 움직이지 않는다. 첫 쪽 위에 화 머리를, 본문이 끝나면 화 끝 블록을 따로 한 쪽에 둔다. 쪽 나누기·읽은 자리·
 * 넘김 전환은 `usePagedReader` 가, 탭·손짓·휠·키는 `usePageInput` 이 맡는다.
 *
 * 판형 안의 글자·간격은 전부 px 다(rem 이면 브라우저 기본 글자 크기가 쪽 수를 바꾼다). 판형 상자는 transform 이
 * 레이아웃 크기를 줄이지 않으므로, 화면 크기의 바깥 상자가 잘라 담는다 — 그러지 않으면 원래 크기 상자가 창을 넘친다.
 *
 * 마우스·트랙패드 기기에서는 판형 좌우 바깥에 넘김 버튼을 늘 둔다 — 보이지 않는 탭 영역 말고는 넘길 곳을 알려 주는
 * 단서가 없어서다. 정지 색을 컨트롤 보더와 같은 `input` 으로 낮춰 읽는 동안 눈에 걸리지 않게 하고, 가리키거나
 * 포커스하면 본문 색으로 밝힌다. 버튼은 본문 상자 밖 형제라 누름이 넘김 손짓으로 읽히지 않고, 바보다 아래에 놓여
 * 바가 열리면 바가 위다. 터치 기기에는 넘김 버튼이 없다 — 탭 영역·스와이프·아래 바의 쪽 슬라이더로 넘긴다.
 *
 * 넘기는 손짓과 텍스트 선택은 같은 끌기라 함께 살 수 없어 본문 선택을 끈다(복사는 스크롤 모드에서). 가로 오버스크롤은
 * 막아 끝 쪽에서 더 끌어도 브라우저의 뒤로 가기 손짓으로 새지 않게 하고, 터치는 핀치 확대만 브라우저에 남긴다 — 가로
 * 끌기는 넘김이 직접 받는다.
 */
export function PagedEpisodeBody({
  ref,
  novel,
  summary,
  episodeLabel,
  paragraphs,
  next,
  fit,
  typography,
  readingPosition,
  onPositionChange,
  isSettingsOpen,
  settingsPanelRef,
  onBodyTap,
  onOpenToc,
}: PagedEpisodeBodyProps) {
  const isFinePointer = useIsFinePointer();
  const reader = usePagedReader({
    session: readingPosition,
    paragraphCount: paragraphs.length,
    fit,
    typographyKey: `${typography.fontSizePx}/${typography.lineHeight}`,
  });

  const wheelRootRef = useRef<HTMLDivElement>(null);
  const input = usePageInput({
    viewportRef: reader.viewportRef,
    wheelRootRef,
    handle: reader.handle,
    directMove: reader.directMove,
    // 손짓 거리는 화면 px 라 판정 기준 폭도 화면 px 로 준다.
    pageWidth: fit.width,
    screenCount: reader.position.screenCount,
    isSettingsOpen,
    settingsPanelRef,
    onBodyTap,
  });
  const { screen, screenCount } = reader.position;
  const buttonTop = fit.top + fit.height / 2 - PAGE_BUTTON_SIZE_PX / 2;

  useImperativeHandle(ref, () => reader.handle);

  useEffect(() => {
    onPositionChange(reader.position);
  }, [reader.position]);

  return (
    // 휠은 본문 상자와 거터 넘김 버튼을 함께 담은 이 범위에서 받는다. 상자를 만들지 않는 감싸개라 배치에는 영향이 없다.
    <div ref={wheelRootRef} className="contents">
      {/* 넘김 버튼은 DOM 에서 본문보다 앞에 둔다(고정 위치라 화면 자리는 같다). Tab 순서가 "메뉴 열기 → 이전 쪽 → 다음 쪽
          → 화 머리 링크 → …" 가 되게 — 뒤에 두면 보이는 "다음 쪽" 으로 가려던 Tab 이 화 끝의 "다음 화" 링크를 먼저
          거치고, 브라우저가 그 링크를 보이려고 화 끝 화면으로 옮겨 화가 다 읽음으로 저장된다. */}
      {isFinePointer && screenCount > 0 && (
        <>
          <PageTurnButton
            direction="previous"
            isBlocked={screen === 0}
            onTurn={reader.handle.previous}
            className="fixed z-20 text-input focus-visible:text-foreground"
            style={{ left: fit.left - PAGE_BUTTON_GAP_PX - PAGE_BUTTON_SIZE_PX, top: buttonTop }}
          />
          <PageTurnButton
            direction="next"
            isBlocked={screen === screenCount - 1}
            onTurn={reader.handle.next}
            className="fixed z-20 text-input focus-visible:text-foreground"
            style={{ left: fit.left + fit.width + PAGE_BUTTON_GAP_PX, top: buttonTop }}
          />
        </>
      )}

      <main
        ref={reader.viewportRef}
        className="fixed inset-0 touch-pinch-zoom overflow-hidden data-dragging:cursor-grabbing"
        onPointerDown={input.onPointerDown}
        onPointerMove={input.onPointerMove}
        onPointerUp={input.onPointerUp}
        onPointerCancel={input.onPointerCancel}
        onClickCapture={input.onClickCapture}
        onDragStart={input.onDragStart}
      >
        {/* 화면 크기의 바깥 상자 — 배율을 건 판형 묶음을 잘라 담는다. */}
        <div
          className="absolute overflow-hidden"
          style={{ left: fit.left, top: fit.top, width: fit.width, height: fit.height }}
        >
          <div
            ref={reader.scrollerRef}
            className="absolute top-0 left-0 origin-top-left touch-pinch-zoom overflow-hidden overscroll-x-none select-none"
            style={{
              width: fit.columnCount * PAGE_FORMAT_WIDTH_PX,
              height: PAGE_FORMAT_HEIGHT_PX,
              paddingTop: PAGE_FORMAT_PADDING_PX,
              transform: `scale(${fit.scale})`,
            }}
          >
            {/* 다단은 블록 요소에 건다 — flex 요소에는 단이 걸리지 않는다. 단 크기는 훅이 요소 스타일에 직접 쓴다. */}
            <article ref={reader.columnsRef}>
              <div className="break-inside-avoid" style={{ marginBottom: HEADER_GAP_PX }}>
                <EpisodeHeader novelId={novel.id} novelTitle={novel.title} episodeLabel={episodeLabel} isInPageFormat />
              </div>

              <div
                className="flex flex-col text-foreground"
                style={{
                  gap: typography.paragraphGapPx,
                  fontSize: typography.fontSizePx,
                  lineHeight: typography.lineHeight,
                }}
              >
                {paragraphs.map((paragraph, index) => (
                  // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도
                  // 이 순번으로 저장한다).
                  <p key={index} data-paragraph-index={index} className="whitespace-pre-line text-pretty break-keep">
                    {paragraph}
                  </p>
                ))}
              </div>

              {/* 펼침에서 화 끝 블록이 오른쪽 단에 떨어질 때만 켜지는 빈 단 — 화 끝을 새 펼침의 왼쪽 쪽으로 민다. */}
              <div ref={reader.spacerRef} aria-hidden className="hidden break-before-column" />

              {/* 화 끝은 따로 한 쪽이다. 한 쪽에 이것뿐이라 위에 붙이면 아래가 휑해 세로 가운데에 둔다. */}
              <div ref={reader.endRef} className="flex break-before-column break-inside-avoid flex-col justify-center">
                <EpisodeEnd
                  novelId={novel.id}
                  authorNote={summary.authorNote}
                  next={next}
                  isInPageFormat
                  onOpenToc={onOpenToc}
                />
              </div>
            </article>
          </div>
        </div>
      </main>
    </div>
  );
}
