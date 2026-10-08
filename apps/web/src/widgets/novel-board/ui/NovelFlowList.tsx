import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useState, type ReactNode } from "react";

import { NOTES_NODE_KEY, characterNodeKey, episodeNodeKey, type BoardModel, type CharacterNodeData } from "../model/boardNode";
import type { BoardSelection } from "../model/boardSelection";
import { toFlowListCharacters, toFlowListSections } from "../model/flowList";

import { CharacterCardBody, EpisodeCardBody, NotesCardBody, boardCardClassName } from "./BoardCardBodies";

const TABS = ["episodes", "characters", "notes"] as const;
type FlowListTab = (typeof TABS)[number];
const TAB_LABEL: Record<FlowListTab, string> = { episodes: "화", characters: "인물", notes: "설정" };

type NovelFlowListProps = {
  model: BoardModel;
  /** 인물 목록 상태. 못 받았으면 인물 탭이 다시 시도를 보인다(화 탭은 그대로). */
  characterStatus: "ready" | "loading" | "error";
  onRetryCharacters: () => void;
  onSelect: (selection: BoardSelection) => void;
};

const ROW_CLASS = "w-full min-h-11 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * 좁은 화면(lg 미만)의 편집 보드 — 캔버스 대신 같은 데이터를 세로 흐름 목록으로 보인다. 화(묶음마다 머리)·인물·설정
 * 탭이고, 행을 누르면 목록 자리가 그 대상의 패널 화면으로 바뀐다. 행은 캔버스 카드와 같은 내용·같은 껍데기다. 화 순서는
 * 캔버스의 Tab 순서(읽는 순서)와 같다.
 *
 * 패널 화면이 떠 있는 동안에도 호출부는 이 목록을 숨긴 채 마운트해 둔다 — 돌아오면 고른 탭과 스크롤 자리가 그대로다.
 * 행마다 `data-board-key` 를 달아, 돌아올 때 호출부가 고르던 행으로 포커스를 돌려준다.
 */
export function NovelFlowList({ model, characterStatus, onRetryCharacters, onSelect }: NovelFlowListProps) {
  const [tab, setTab] = useState<FlowListTab>("episodes");
  const sections = toFlowListSections(model);
  const characters = toFlowListCharacters(model);

  return (
    <Tabs value={tab} onValueChange={(value) => setTab(TABS.find((item) => item === value) ?? "episodes")} className="gap-4">
      <TabsList variant="line">
        {TABS.map((item) => (
          <TabsTrigger key={item} value={item}>
            {TAB_LABEL[item]}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="episodes" className="flex flex-col gap-6">
        {sections.length === 0 ? (
          <EmptyRow>아직 화가 없어요. 대화를 소설로 만들면 화가 여기 차례로 놓여요.</EmptyRow>
        ) : (
          sections.map((section) => (
            <section key={section.key} className="flex flex-col gap-2">
              <h2 className="text-xs text-muted-foreground tabular-nums">{section.label}</h2>
              <ul className="flex flex-col gap-2">
                {section.episodes.map((episode) => (
                  <li key={episode.episodeId}>
                    <button
                      type="button"
                      data-board-key={episodeNodeKey(episode.episodeId)}
                      className={cn(boardCardClassName({ isSelected: false }), ROW_CLASS)}
                      onClick={() => onSelect({ kind: "episode", id: episode.episodeId })}
                    >
                      <EpisodeCardBody data={episode} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </TabsContent>

      <TabsContent value="characters">
        <CharacterRows
          characters={characters}
          status={characterStatus}
          onRetry={onRetryCharacters}
          onSelect={(characterId) => onSelect({ kind: "character", id: characterId })}
        />
      </TabsContent>

      <TabsContent value="notes">
        <button
          type="button"
          data-board-key={NOTES_NODE_KEY}
          className={cn(boardCardClassName({ isSelected: false, isDashed: model.notes.trim() === "" }), ROW_CLASS)}
          onClick={() => onSelect({ kind: "notes" })}
        >
          <NotesCardBody data={{ notes: model.notes }} />
        </button>
      </TabsContent>
    </Tabs>
  );
}

type CharacterRowsProps = {
  characters: CharacterNodeData[];
  status: NovelFlowListProps["characterStatus"];
  onRetry: () => void;
  onSelect: (characterId: string) => void;
};

/** 인물 탭 — 받는 중·실패·빈 목록·목록이 배타적이라 순서대로 일찍 돌려준다. */
function CharacterRows({ characters, status, onRetry, onSelect }: CharacterRowsProps) {
  if (status === "error") {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm break-keep text-muted-foreground">인물을 불러오지 못했어요.</p>
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          다시 시도
        </Button>
      </div>
    );
  }
  if (status === "loading") {
    return (
      <div aria-hidden className="flex flex-col gap-2">
        <div className="h-22 animate-pulse rounded-xl bg-muted" />
        <div className="h-22 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }
  if (characters.length === 0) {
    return <EmptyRow>아직 인물이 없어요. 화를 만들면 나온 인물이 여기 카드로 모여요.</EmptyRow>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {characters.map((character) => (
        <li key={character.characterId}>
          <button
            type="button"
            data-board-key={characterNodeKey(character.characterId)}
            className={cn(boardCardClassName({ isSelected: false }), ROW_CLASS)}
            onClick={() => onSelect(character.characterId)}
          >
            <CharacterCardBody data={character} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function EmptyRow({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed border-border p-4 text-sm break-keep text-muted-foreground">{children}</p>
  );
}
