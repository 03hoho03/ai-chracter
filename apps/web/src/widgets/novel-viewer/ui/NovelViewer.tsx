import { Button } from "@ai-character-chat/ui/components/button";
import { useAtomValue } from "jotai";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import {
  toAdjacentChapters,
  toEpisodeLabel,
  type NovelChapterResponse,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";

import { toEscapeTarget } from "../lib/escapeTarget";
import { VIEWER_BAR_SPACE_PX } from "../lib/pageFit";
import { toPageTypography } from "../lib/pageFormat";
import { readerTypographyClassName } from "../lib/readerTypography";
import { toEpisodeScrollProgress } from "../lib/readingProgress";
import { toChapterSavedReadingPosition } from "../lib/savedReadingPosition";
import { useIsFinePointer } from "../lib/useIsFinePointer";
import { useScreenWakeLock } from "../lib/useScreenWakeLock";
import { readerSettingsAtom } from "../model/readerSettings";
import { useChromeVisibility } from "../model/useChromeVisibility";
import type { PagedPosition, PagedReaderHandle } from "../model/usePagedReader";
import { usePageFit } from "../model/usePageFit";
import { useReadingPosition } from "../model/useReadingPosition";
import { PagedEpisodeBody } from "./PagedEpisodeBody";
import { ScrollEpisodeBody } from "./ScrollEpisodeBody";
import { ViewerBottomBar } from "./ViewerBottomBar";
import { ViewerSettingsPanel } from "./ViewerSettingsPanel";
import { ViewerTocSheet } from "./ViewerTocSheet";
import { ViewerTopBar } from "./ViewerTopBar";

/** 배율이 하한 밑이라 스크롤 모드로 보일 때의 안내. 같은 id 라 창을 여러 번 돌려도 하나만 뜬다. */
const SCROLL_FORCED_TOAST_ID = "novel-viewer-scroll-forced";

type NovelViewerProps = {
  novel: NovelDetailResponse;
  /** 지금 화의 목차 정보(제목·요약·작가의 말·읽음). 화 조회 응답에는 이것들이 없다. */
  summary: NovelChapterSummary;
  /** 지금 화의 본문. 문단은 서버가 나눈 그대로 쓴다. */
  chapter: NovelChapterResponse;
};

/**
 * 소설 화 읽기 화면(몰입 뷰어). 전역 헤더·사이트 푸터 없이 본문만 있고, 본문을 탭하거나 "메뉴 열기"를 누를 때만
 * 위·아래 바가 나타난다(DESIGN.md Navigation 절의 화 읽기 예외). 본문은 보기 설정의 넘김 방식에 따라 고정 판형의
 * 쪽을 좌우로 넘기는 화면(페이지 모드 — 바 자리를 늘 비워 두어 바가 글을 가리지 않는다)이거나 문서 스크롤(스크롤
 * 모드 — 바가 본문 위에 겹친다)이다.
 *
 * 읽은 자리 저장·바·보기 설정은 여기(화 단위)에 있고 본문만 넘김 방식에 따라 바뀐다 — 같은 화 안에서 방식을 바꿔도
 * 화를 떠나는 처리가 돌지 않고, 새 본문은 읽던 문단에서 이어 열리며, 설정 패널의 포커스도 남는다.
 *
 * 화를 옮기면 호출부가 화 id 로 key 를 바꿔 새로 마운트한다 — 바 숨김·읽은 자리 되돌리기·저장이 화마다 처음부터
 * 시작하고, 떠나는 화의 기다리던 저장이 그 화 id 로 나간다.
 */
export function NovelViewer({ novel, summary, chapter }: NovelViewerProps) {
  const settings = useAtomValue(readerSettingsAtom);
  const topBarId = useId();
  const bottomBarId = useId();
  const settingsPanelId = useId();
  const settingsPanelRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const tocButtonRef = useRef<HTMLButtonElement>(null);
  const tocOpenerRef = useRef<HTMLElement | null>(null);
  const pagedReaderRef = useRef<PagedReaderHandle>(null);
  const isFinePointer = useIsFinePointer();
  const pageFit = usePageFit(isFinePointer);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [progress, setProgress] = useState(0);
  const [pagedPosition, setPagedPosition] = useState<PagedPosition>({
    screen: 0,
    screenCount: 0,
    pageLabel: undefined,
  });
  const chrome = useChromeVisibility({ onHide: () => setIsSettingsOpen(false) });
  const { previous, next } = toAdjacentChapters(novel.chapters, summary.ordinal);
  const paragraphs = chapter.revision.paragraphs;
  const episodeLabel = toEpisodeLabel(summary);
  const { saved, isAbsenceKnown } = toChapterSavedReadingPosition(summary, novel.lastRead);
  const { fit } = pageFit;
  // 판형 배율이 하한 밑인 화면(가로로 눕힌 폰, 아주 낮은 창)은 글자가 너무 작아 이 기기에서만 스크롤 모드로 보인다.
  // 저장된 넘김 방식은 바꾸지 않는다 — 세로로 돌리거나 창을 키우면 페이지 모드로 돌아온다. 안내 문구는 기기 종류와
  // 무관하게 쓴다(마우스 기기의 낮은 창에는 돌릴 화면이 없다).
  const isScrollForced = settings.mode === "page" && fit?.isBelowMinimum === true;
  const mode = isScrollForced ? "scroll" : settings.mode;
  const inEpisodeLocation = mode === "scroll" ? `${Math.round(progress * 100)}%` : pagedPosition.pageLabel;
  const location = `${summary.ordinal}/${novel.chapters.length}화${inEpisodeLocation === undefined ? "" : ` · ${inEpisodeLocation}`}`;

  useEffect(() => {
    if (isScrollForced) toast("화면이 작아 이 기기에서는 스크롤로 보여요. 화면이 넉넉해지면 페이지로 돌아가요.", { id: SCROLL_FORCED_TOAST_ID });
  }, [isScrollForced]);

  // 두 넘김 방식 모두 읽는 동안이라 본문이 아니라 여기서 잡는다 — 방식을 바꿔도 놓았다 다시 잡지 않는다.
  useScreenWakeLock(settings.keepScreenOn);

  const readingPosition = useReadingPosition({
    novelId: novel.id,
    chapterId: chapter.id,
    revisionId: chapter.revision.id,
    paragraphCount: paragraphs.length,
    // 화마다 읽던 자리가 상세에 실려 온다 — 마지막으로 읽은 화가 아니어도 그 화의 자리로 연다.
    saved,
    isAbsenceKnown,
    wasFinished: summary.finishedReading,
  });

  // 스크롤 모드의 화 안 진행률은 바에만 보이므로 바가 보이는 동안만 스크롤을 따라 다시 잰다(읽는 동안 다시
  // 그리지 않게).
  useEffect(() => {
    if (!chrome.isVisible || mode !== "scroll") return;
    let frame: number | undefined;
    function measure() {
      frame = undefined;
      setProgress(
        toEpisodeScrollProgress({
          scrollTop: window.scrollY,
          scrollHeight: document.documentElement.scrollHeight,
          clientHeight: window.innerHeight,
        }),
      );
    }
    function handleScroll() {
      if (frame === undefined) frame = requestAnimationFrame(measure);
    }
    measure();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, [chrome.isVisible, mode]);

  // 보기 설정을 열면 첫 줄(넘김 방식)의 고른 칩으로 포커스를 옮긴다(단일 선택 그룹은 고른 칩이 Tab 정지점이다).
  useEffect(() => {
    if (!isSettingsOpen) return;
    settingsPanelRef.current?.querySelector<HTMLElement>('[data-state="on"]')?.focus();
  }, [isSettingsOpen]);

  // Esc 는 가장 위의 것부터 하나만 닫는다(`toEscapeTarget`). 창의 캡처 단계에서 듣는 이유: 시트는 문서 캡처 단계에서 Esc 를 받아 닫히고, 그 렌더가 같은 키 입력 도중 커밋되면 문서에 다시
  // 단 처리기가 "시트 닫힘"을 보고 바까지 숨겼다(포커스가 숨은 바와 함께 `<body>` 로 떨어졌다). 창 캡처는 시트보다
  // 먼저 돌아 누른 순간의 열림 상태로 판단하고, 그 사이 다시 단 처리기는 이미 지난 단계라 같은 키에 불리지 않는다.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      const target = toEscapeTarget({ isTocOpen, isSettingsOpen, isChromeVisible: chrome.isVisible });
      if (target === "settings") closeSettings();
      else if (target === "chrome") chrome.hide();
    }
    window.addEventListener("keydown", handleKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", handleKeyDown, { capture: true });
  });

  function closeSettings() {
    const active = document.activeElement;
    if (active !== null && settingsPanelRef.current?.contains(active) === true) settingsButtonRef.current?.focus();
    setIsSettingsOpen(false);
  }

  function handleBodyTap() {
    if (isSettingsOpen) {
      closeSettings();
      return;
    }
    if (chrome.isVisible) chrome.hide();
    else chrome.show({ focusTopBar: false });
  }

  function openToc(opener: HTMLElement | null) {
    tocOpenerRef.current = opener;
    setIsTocOpen(true);
  }

  return (
    <>
      {/* 창 크기와 safe-area 를 재는 보이지 않는 탐침(`usePageFit`). */}
      <div
        ref={pageFit.probeRef}
        aria-hidden
        className="pointer-events-none invisible fixed inset-0"
        style={{
          padding: "env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)",
        }}
      />

      {/* 문서의 첫 Tab 정지점. 평소에는 보이지 않고 키보드 포커스를 받을 때만 왼쪽 위에 나타난다 — 숨은 바는 `inert`
          라 Tab 으로 닿지 않으므로 키보드 사용자는 이 버튼으로 바를 연다.
          포커스 때는 `sr-only` 를 아예 걸지 않는다(`not-focus-visible:`) — `not-sr-only` 로 풀면 그 높이·패딩 초기화가
          버튼 크기를 덮어 납작해진다. 자리는 감싼 요소의 여백으로 잡고 버튼의 전환을 끈다 — 그대로 두면 `sr-only` 가
          풀리는 순간 1px 에서 제 크기로, 여백이 제자리로 미끄러진다.
          바가 열려 있으면 위 바 아래로 내려 뒤로 버튼·화 제목을 가리지 않는다 — 내리는 거리는 바와 같은 px 상수다(rem
          이면 브라우저 기본 글자 크기에 따라 바와 겹치거나 떨어진다). 바와 같이 좌우 safe-area 도 더해 가로로
          눕힌 노치 폰에서 버튼이 노치 밑에 깔리지 않게 한다. */}
      <div
        className="pointer-events-none fixed inset-x-0 top-0 z-40 px-safe pt-safe"
        style={chrome.isVisible ? { marginTop: VIEWER_BAR_SPACE_PX } : undefined}
      >
        <div className="p-4">
          <Button
            ref={chrome.menuButtonRef}
            type="button"
            variant="outline"
            size="sm"
            aria-expanded={chrome.isVisible}
            aria-controls={`${topBarId} ${bottomBarId}`}
            className="pointer-events-auto not-focus-visible:sr-only motion-safe:transition-none"
            onClick={() => (chrome.isVisible ? chrome.hide() : chrome.show({ focusTopBar: true }))}
          >
            {chrome.isVisible ? "메뉴 닫기" : "메뉴 열기"}
          </Button>
        </div>
      </div>

      <ViewerTopBar
        ref={chrome.topBarRef}
        id={topBarId}
        novelId={novel.id}
        episodeLabel={episodeLabel}
        location={location}
        isVisible={chrome.isVisible}
        isSettingsOpen={isSettingsOpen}
        settingsPanelId={settingsPanelId}
        tocButtonRef={tocButtonRef}
        settingsButtonRef={settingsButtonRef}
        onOpenToc={() => openToc(tocButtonRef.current)}
        onToggleSettings={() => (isSettingsOpen ? closeSettings() : setIsSettingsOpen(true))}
      />

      {/* 아래 바는 DOM 에서 본문보다 앞에 둔다(고정 위치라 화면 자리는 같고 쌓임은 z 값이 정한다). 바를 연 키보드
          사용자가 위 바에서 Tab 으로 쪽 이동 슬라이더에 가는 길에 화 끝 링크를 거치지 않게 — 거치면 브라우저가 그
          링크를 보이려고 화 끝 화면으로 옮겨 화가 다 읽음으로 저장된다. */}
      <ViewerBottomBar
        ref={chrome.bottomBarRef}
        id={bottomBarId}
        novelId={novel.id}
        position={
          mode === "scroll"
            ? { mode: "scroll", progress }
            : {
                mode: "page",
                screen: pagedPosition.screen,
                screenCount: pagedPosition.screenCount,
                pageLabel: pagedPosition.pageLabel,
                onSeek: (screen) => pagedReaderRef.current?.goTo(screen),
              }
        }
        previous={previous}
        next={next}
        isVisible={chrome.isVisible}
        settingsPanel={isSettingsOpen ? <ViewerSettingsPanel ref={settingsPanelRef} id={settingsPanelId} isScrollForced={isScrollForced} /> : null}
      />

      {/* 판형을 창에 맞추기 전에는 본문을 그리지 않는다 — 칠하기 전에 정해지므로 빈 화면이 보이지는 않는다. */}
      {fit !== undefined && mode === "page" && (
        <PagedEpisodeBody
          ref={pagedReaderRef}
          novel={novel}
          summary={summary}
          episodeLabel={episodeLabel}
          paragraphs={paragraphs}
          next={next}
          fit={fit}
          typography={toPageTypography(settings)}
          readingPosition={readingPosition}
          onPositionChange={setPagedPosition}
          isSettingsOpen={isSettingsOpen}
          settingsPanelRef={settingsPanelRef}
          onBodyTap={handleBodyTap}
          onOpenToc={openToc}
        />
      )}
      {fit !== undefined && mode === "scroll" && (
        <ScrollEpisodeBody
          novel={novel}
          summary={summary}
          episodeLabel={episodeLabel}
          paragraphs={paragraphs}
          next={next}
          typographyClassName={readerTypographyClassName(settings)}
          readingPosition={readingPosition}
          onPointerDown={chrome.handlePointerDown}
          onPointerUp={(event) => chrome.handlePointerUp(event, handleBodyTap)}
          onOpenToc={openToc}
        />
      )}

      <ViewerTocSheet
        novel={novel}
        currentChapterId={chapter.id}
        open={isTocOpen}
        onOpenChange={setIsTocOpen}
        returnFocusTo={() => tocOpenerRef.current}
      />
    </>
  );
}
