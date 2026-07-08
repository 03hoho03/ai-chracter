import type { components } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useAtom } from "jotai";
import { useForm, useWatch } from "react-hook-form";

import {
  characterBuilderSchema,
  serverToForm,
  type CharacterBuilderFormValues,
} from "../../../features/build-character";
import { characterBuilderActiveTabAtom, type CharacterBuilderTab } from "../model/activeTabAtom";
import { ProfileTab } from "./ProfileTab";

type CharacterDraftResponse = components["schemas"]["CharacterDraftResponse"];

const TABS: { id: CharacterBuilderTab; label: string }[] = [
  { id: "profile", label: "프로필" },
  { id: "intro", label: "인트로" },
  { id: "prompt", label: "프롬프트" },
  { id: "advanced", label: "고급기능" },
  { id: "detail", label: "상세" },
];

function TabPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-20 text-center">
      <p className="text-sm text-muted-foreground">다음 스토리에서 준비할게요.</p>
    </div>
  );
}

/** techspec-builder-character.md §0/§1 — 5탭 단일 useForm 셸. 탭은 뷰 전환일 뿐, 발행/자동저장
 * 연동은 US-105가 담당한다 — 여기서는 발행 버튼의 활성/비활성만 스키마 유효성으로 판단한다. */
export function CharacterBuilderShell({ data }: { data: CharacterDraftResponse }) {
  const [activeTab, setActiveTab] = useAtom(characterBuilderActiveTabAtom);
  const form = useForm<CharacterBuilderFormValues>({ defaultValues: serverToForm(data) });
  const values = useWatch({ control: form.control });
  const canPublish = characterBuilderSchema.safeParse(values).success;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">캐릭터 만들기</h1>
        <Button disabled={!canPublish}>발행</Button>
      </header>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as CharacterBuilderTab)}>
        <TabsList variant="line">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="profile">
          <ProfileTab form={form} />
        </TabsContent>
        <TabsContent value="intro">
          <TabPlaceholder />
        </TabsContent>
        <TabsContent value="prompt">
          <TabPlaceholder />
        </TabsContent>
        <TabsContent value="advanced">
          <TabPlaceholder />
        </TabsContent>
        <TabsContent value="detail">
          <TabPlaceholder />
        </TabsContent>
      </Tabs>
    </main>
  );
}
