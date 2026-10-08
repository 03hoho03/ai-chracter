import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { useAtomValue } from "jotai";
import { ChevronLeft } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import {
  toAdjacentChapters,
  toEpisodeLabel,
  type NovelChapterResponse,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";

import { toEscapeTarget } from "../lib/escapeTarget";
import { readerTypographyClassName } from "../lib/readerTypography";
import { toEpisodeScrollProgress } from "../lib/readingProgress";
import { readerSettingsAtom } from "../model/readerSettings";
import { useChromeVisibility } from "../model/useChromeVisibility";
import { useReadingPosition } from "../model/useReadingPosition";
import { EpisodeEnd } from "./EpisodeEnd";
import { PreviousSummary } from "./PreviousSummary";
import { ViewerBottomBar } from "./ViewerBottomBar";
import { ViewerSettingsPanel } from "./ViewerSettingsPanel";
import { ViewerTocSheet } from "./ViewerTocSheet";
import { ViewerTopBar } from "./ViewerTopBar";

type NovelViewerProps = {
  novel: NovelDetailResponse;
  /** 지금 화의 목차 정보(제목·요약·작가의 말·읽음). 화 조회 응답에는 이것들이 없다. */
  summary: NovelChapterSummary;
  /** 지금 화의 본문. 문단은 서버가 나눈 그대로 쓴다. */
  chapter: NovelChapterResponse;
};

/**
 * 소설 화 읽기 화면(몰입 뷰어). 전역 헤더·사이트 푸터 없이 본문만 있는 문서 스크롤 화면이고, 본문을 탭하거나 "메뉴
 * 열기"를 누를 때만 위·아래 바가 본문 위에 겹쳐 나타난다(DESIGN.md Navigation 절의 화 읽기 예외).
 *
 * 화를 옮기면 호출부가 화 id 로 key 를 바꿔 새로 마운트한다 — 바 숨김·읽은 자리 되돌리기·저장이 화마다 처음부터
 * 시작하고, 떠나는 화의 기다리던 저장이 그 화 id 로 나간다.
 */
export function NovelViewer({ novel, summary, chapter }: NovelViewerProps) {
  const settings = useAtomValue(readerSettingsAtom);
  const topBarId = useId();
  const bottomBarId = useId();
  const settingsPanelId = useId();
  const articleRef = useRef<HTMLElement>(null);
  const settingsPanelRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const tocButtonRef = useRef<HTMLButtonElement>(null);
  const tocOpenerRef = useRef<HTMLElement | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [progress, setProgress] = useState(0);
  const chrome = useChromeVisibility({ onHide: () => setIsSettingsOpen(false) });
  const { previous, next } = toAdjacentChapters(novel.chapters, summary.ordinal);
  const paragraphs = chapter.revision.paragraphs;
  const lastRead = novel.lastRead;
  const episodeLabel = toEpisodeLabel(summary);

  useReadingPosition({
    novelId: novel.id,
    chapterId: chapter.id,
    revisionId: chapter.revision.id,
    paragraphCount: paragraphs.length,
    saved: lastRead !== null && lastRead.chapterId === chapter.id ? lastRead : undefined,
    wasFinished: summary.finishedReading,
    containerRef: articleRef,
  });

  // 화 안 진행률은 아래 바에만 보이므로 바가 보이는 동안만 스크롤을 따라 다시 잰다(읽는 동안 다시 그리지 않게).
  useEffect(() => {
    if (!chrome.isVisible) return;
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
  }, [chrome.isVisible]);

  // 보기 설정을 열면 지금 고른 글자 크기 칩으로 포커스를 옮긴다(단일 선택 그룹은 고른 칩이 Tab 정지점이다).
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
      {/* 문서의 첫 Tab 정지점. 평소에는 보이지 않고 키보드 포커스를 받을 때만 왼쪽 위에 나타난다 — 숨은 바는 `inert`
          라 Tab 으로 닿지 않으므로 키보드 사용자는 이 버튼으로 바를 연다.
          포커스 때는 `sr-only` 를 아예 걸지 않는다(`not-focus-visible:`) — `not-sr-only` 로 풀면 그 높이·패딩 초기화가
          버튼 크기를 덮어 납작해진다. 자리는 감싼 요소의 여백으로 잡고 버튼의 전환을 끈다 — 그대로 두면 `sr-only` 가
          풀리는 순간 1px 에서 제 크기로, 여백이 제자리로 미끄러진다.
          바가 열려 있으면 위 바 아래로 내려 뒤로 버튼·화 제목을 가리지 않는다. */}
      <div className={cn("pointer-events-none fixed inset-x-0 top-0 z-40 pt-safe", chrome.isVisible && "mt-14")}>
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
        isVisible={chrome.isVisible}
        isSettingsOpen={isSettingsOpen}
        settingsPanelId={settingsPanelId}
        tocButtonRef={tocButtonRef}
        settingsButtonRef={settingsButtonRef}
        onOpenToc={() => openToc(tocButtonRef.current)}
        onToggleSettings={() => (isSettingsOpen ? closeSettings() : setIsSettingsOpen(true))}
      />

      <main
        className="min-h-dvh pt-10-safe pb-28"
        onPointerDown={chrome.handlePointerDown}
        onPointerUp={(event) => chrome.handlePointerUp(event, handleBodyTap)}
      >
        <article ref={articleRef} className={cn("mx-auto flex max-w-prose flex-col gap-8", readerTypographyClassName(settings))}>
          <header className="flex flex-col gap-2">
            {/* 바가 숨어 있어도 늘 있는 출구. */}
            <Link
              to="/novels/$novelId"
              params={{ novelId: novel.id }}
              className="flex w-fit items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <ChevronLeft aria-hidden className="size-4 shrink-0" />
              <span className="min-w-0 truncate">{novel.title ?? "제목 미정"}</span>
            </Link>
            <h1 className="text-2xl font-bold tracking-tight text-balance break-keep text-foreground">{episodeLabel}</h1>
            <p className="text-xs text-muted-foreground tabular-nums">{summary.charCount.toLocaleString()}자</p>
          </header>

          {previous !== undefined && previous.summary !== null && previous.summary !== "" && (
            <PreviousSummary ordinal={previous.ordinal} summary={previous.summary} />
          )}

          <div className="flex flex-col gap-4 text-foreground">
            {paragraphs.map((paragraph, index) => (
              // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도
              // 이 순번으로 저장한다).
              <p key={index} data-paragraph-index={index} className="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">
                {paragraph}
              </p>
            ))}
          </div>

          <EpisodeEnd novelId={novel.id} authorNote={summary.authorNote} next={next} onOpenToc={openToc} />
        </article>
      </main>

      <ViewerBottomBar
        ref={chrome.bottomBarRef}
        id={bottomBarId}
        novelId={novel.id}
        ordinal={summary.ordinal}
        totalCount={novel.chapters.length}
        progress={progress}
        previous={previous}
        next={next}
        isVisible={chrome.isVisible}
        settingsPanel={isSettingsOpen ? <ViewerSettingsPanel ref={settingsPanelRef} id={settingsPanelId} /> : null}
      />

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
