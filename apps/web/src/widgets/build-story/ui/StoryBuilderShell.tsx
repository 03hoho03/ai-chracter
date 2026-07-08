import type { components } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useAtom } from "jotai";
import { useForm, useWatch } from "react-hook-form";

import { storyBuilderSchema, serverToForm, type StoryBuilderFormValues } from "../../../features/build-story";
import { storyBuilderActiveTabAtom, type StoryBuilderTab } from "../model/activeTabAtom";
import { EndingTab } from "./EndingTab";
import { KeywordNoteTab } from "./KeywordNoteTab";
import { ProfileTab } from "./ProfileTab";
import { RegistrationTab } from "./RegistrationTab";
import { SettingTab } from "./SettingTab";
import { ShortcutTab } from "./ShortcutTab";
import { StartingSetupTab } from "./StartingSetupTab";
import { StatTab } from "./StatTab";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];

const TABS: { id: StoryBuilderTab; label: string }[] = [
  { id: "profile", label: "프로필" },
  { id: "setting", label: "설정" },
  { id: "startingSetup", label: "시작설정" },
  { id: "stat", label: "스탯" },
  { id: "keywordNote", label: "키워드북" },
  { id: "shortcut", label: "단축어" },
  { id: "ending", label: "엔딩" },
  { id: "registration", label: "등록" },
];

/** techspec-builder-story.md §0/§1 — 8탭 단일 useForm 셸. 탭은 뷰 전환일 뿐, 발행/자동저장
 * 연동은 US-114가 담당한다 — 여기서는 발행 버튼의 활성/비활성만 스키마 유효성으로 판단한다. */
export function StoryBuilderShell({ data }: { data: StoryDraftResponse }) {
  const [activeTab, setActiveTab] = useAtom(storyBuilderActiveTabAtom);
  const form = useForm<StoryBuilderFormValues>({ defaultValues: serverToForm(data) });
  const values = useWatch({ control: form.control });
  const canPublish = storyBuilderSchema.safeParse(values).success;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">스토리 만들기</h1>
        <Button disabled={!canPublish}>발행</Button>
      </header>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as StoryBuilderTab)}>
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
        <TabsContent value="setting">
          <SettingTab form={form} />
        </TabsContent>
        <TabsContent value="startingSetup">
          <StartingSetupTab form={form} />
        </TabsContent>
        <TabsContent value="stat">
          <StatTab form={form} />
        </TabsContent>
        <TabsContent value="keywordNote">
          <KeywordNoteTab form={form} />
        </TabsContent>
        <TabsContent value="shortcut">
          <ShortcutTab form={form} />
        </TabsContent>
        <TabsContent value="ending">
          <EndingTab form={form} />
        </TabsContent>
        <TabsContent value="registration">
          <RegistrationTab form={form} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
