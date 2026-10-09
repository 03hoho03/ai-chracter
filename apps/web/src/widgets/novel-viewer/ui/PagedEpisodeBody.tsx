import { cn } from "@ai-character-chat/ui/lib/utils";
import { useEffect, useImperativeHandle, useRef, type Ref, type RefObject } from "react";

import type { NovelChapterSummary, NovelDetailResponse } from "@/entities/novel";

import { useIsFinePointer } from "../lib/useIsFinePointer";
import { usePagedReader, type PagedPosition, type PagedReaderHandle } from "../model/usePagedReader";
import { usePageInput } from "../model/usePageInput";
import type { ReadingPositionSession } from "../model/useReadingPosition";
import { EpisodeEnd } from "./EpisodeEnd";
import { EpisodeHeader } from "./EpisodeHeader";
import { PageTurnButton } from "./PageTurnButton";

/** `max-w-prose` 를 재는 탐침의 폭. 상한이 늘 걸리도록 어떤 창보다 넓게 둔다. */
const PROSE_PROBE_WIDTH_PX = 10_000;
/** 넘김 버튼과 쪽 상자 사이 간격, 버튼 크기(px). 쪽 폭을 정할 때 비워 둔 거터(바깥 8 + 버튼 40 + 안쪽 8) 안에 놓인다. */
const PAGE_BUTTON_GAP_PX = 8;
const PAGE_BUTTON_SIZE_PX = 40;

type PagedEpisodeBodyProps = {
  ref?: Ref<PagedReaderHandle>;
  novel: NovelDetailResponse;
  summary: NovelChapterSummary;
  episodeLabel: string;
  paragraphs: readonly string[];
  next: NovelChapterSummary | undefined;
  /** 보기 설정(글자 크기·줄 간격)에서 나온 본문 조판 클래스. 좌우 여백은 탐침의 고정 패딩을 잰다. */
  typographyClassName: string;
  readingPosition: ReadingPositionSession;
  onPositionChange: (position: PagedPosition) => void;
  isSettingsOpen: boolean;
  settingsPanelRef: RefObject<HTMLElement | null>;
  /** 본문 가운데 탭 — 보기 설정이 열려 있으면 그것만 닫고, 아니면 바를 여닫는다. */
  onBodyTap: () => void;
  onOpenToc: (opener: HTMLElement) => void;
};

/**
 * 쪽을 좌우로 넘겨 읽는 화 본문(페이지 모드). 뷰포트를 채우는 고정 화면이고, 첫 쪽 위에 화 머리를, 본문이 끝나면 화 끝
 * 블록을 따로 한 화면에 둔다. 쪽 나누기·읽은 자리·넘김 전환은 `usePagedReader` 가, 탭·손짓·휠·키는
 * `usePageInput` 이 맡는다.
 *
 * 마우스·트랙패드 기기에서는 쪽 좌우 거터에 넘김 버튼을 늘 둔다 — 보이지 않는 탭 영역 말고는 넘길 곳을 알려 주는
 * 단서가 없어서다. 정지 색을 컨트롤 보더와 같은 `input` 으로 낮춰 읽는 동안 눈에 걸리지 않게 하고, 가리키거나
 * 포커스하면 본문 색으로 밝힌다. 버튼은 본문 상자 밖 형제라 누름이 넘김 손짓으로 읽히지 않고, 바보다 아래에 놓여
 * 바가 열리면 바가 위다. 터치 기기의 넘김 버튼은 아래 바에 있다.
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
  typographyClassName,
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
    isFinePointer,
    typographyClassName,
  });

  const wheelRootRef = useRef<HTMLDivElement>(null);
  const input = usePageInput({
    viewportRef: reader.viewportRef,
    wheelRootRef,
    handle: reader.handle,
    directMove: reader.directMove,
    pageWidth: reader.frame?.width ?? 0,
    screenCount: reader.position.screenCount,
    isSettingsOpen,
    settingsPanelRef,
    onBodyTap,
  });
  const { screen, screenCount } = reader.position;

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
      {isFinePointer && reader.frame !== undefined && screenCount > 0 && (
        <>
          <PageTurnButton
            direction="previous"
            isBlocked={screen === 0}
            onTurn={reader.handle.previous}
            className="fixed z-20 text-input focus-visible:text-foreground"
            style={{
              left: reader.frame.left - PAGE_BUTTON_GAP_PX - PAGE_BUTTON_SIZE_PX,
              top: reader.frame.top + reader.frame.height / 2 - PAGE_BUTTON_SIZE_PX / 2,
            }}
          />
          <PageTurnButton
            direction="next"
            isBlocked={screen === screenCount - 1}
            onTurn={reader.handle.next}
            className="fixed z-20 text-input focus-visible:text-foreground"
            style={{
              left: reader.frame.left + reader.frame.width + PAGE_BUTTON_GAP_PX,
              top: reader.frame.top + reader.frame.height / 2 - PAGE_BUTTON_SIZE_PX / 2,
            }}
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
        {/* 잴 때만 쓰는 보이지 않는 탐침. 쪽 상자 상한(`max-w-prose`, 글자 폭 단위라 글자 크기·글꼴마다 다르다)과 여백·줄
          높이를 지금 조판 클래스로 잰다. */}
        <div
          ref={reader.probeRef}
          aria-hidden
          className={cn("pointer-events-none invisible absolute top-0 left-0 max-w-prose px-6", typographyClassName)}
          style={{ width: PROSE_PROBE_WIDTH_PX }}
        />
        {/* safe-area 값은 스크립트로 바로 읽을 수 없어 `env()` 를 패딩으로 받은 요소의 계산값으로 읽는다. */}
        <div
          ref={reader.safeAreaProbeRef}
          aria-hidden
          className="pointer-events-none invisible absolute top-0 left-0"
          style={{
            padding: "env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)",
          }}
        />

        {/* 위치·크기는 잰 값이라 훅이 요소 스타일에 직접 쓴다. */}
        <div ref={reader.scrollerRef} className="absolute touch-pinch-zoom overflow-hidden overscroll-x-none select-none">
          {/* 다단은 블록 요소에 건다 — flex 요소에는 단이 걸리지 않는다. */}
          <article ref={reader.columnsRef} className={typographyClassName}>
            <div className="mb-8 break-inside-avoid">
              <EpisodeHeader novelId={novel.id} novelTitle={novel.title} episodeLabel={episodeLabel} />
            </div>

            <div className="flex flex-col gap-4 text-foreground">
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

            {/* 화 끝은 따로 한 화면이다. 한 화면에 이것뿐이라 위에 붙이면 아래가 휑해 세로 가운데에 둔다. */}
            <div ref={reader.endRef} className="flex break-before-column break-inside-avoid flex-col justify-center">
              <EpisodeEnd
                novelId={novel.id}
                authorNote={summary.authorNote}
                next={next}
                hasDivider={false}
                onOpenToc={onOpenToc}
              />
            </div>
          </article>
        </div>
      </main>
    </div>
  );
}
