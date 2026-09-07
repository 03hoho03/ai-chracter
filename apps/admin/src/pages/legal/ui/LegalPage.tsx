import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useState } from "react";

import { isLegalKind, LEGAL_KIND_LABELS, LEGAL_KINDS, type LegalKind } from "../model/legalKind";
import { useLegalDocumentQuery } from "../api/useLegalDocumentQuery";
import { LegalEditor } from "./LegalEditor";

/** 두 탭의 데이터는 항상 함께 불러온다(문서 2개뿐이라 비용이 작다) — 탭을 바꿔도 안 보이는
 * `TabsContent`가 언마운트될 뿐, 로컬 편집 버퍼(`draftBodyByKind`)는 이 컴포넌트에 있어 살아남는다.
 * 그래서 "저장 안 한 편집 내용이 있는데 탭을 바꾸면 잃는다"는 별도 경고 없이 자연히 해결된다. */
export function LegalPage() {
  const [activeKind, setActiveKind] = useState<LegalKind>("terms");
  // 사용자가 아직 손대지 않은 kind는 키가 없다 — 그때는 렌더 중에 서버 초안을 그대로 읽는다.
  const [draftBodyByKind, setDraftBodyByKind] = useState<Partial<Record<LegalKind, string>>>({});

  const termsQuery = useLegalDocumentQuery("terms");
  const privacyQuery = useLegalDocumentQuery("privacy");
  const queryByKind = { terms: termsQuery, privacy: privacyQuery };

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">약관 관리</h1>

      <Tabs
        value={activeKind}
        onValueChange={(value) => {
          if (isLegalKind(value)) setActiveKind(value);
        }}
      >
        <TabsList variant="line">
          {LEGAL_KINDS.map((kind) => (
            <TabsTrigger key={kind} value={kind}>
              {LEGAL_KIND_LABELS[kind]}
            </TabsTrigger>
          ))}
        </TabsList>

        {LEGAL_KINDS.map((kind) => (
          <TabsContent key={kind} value={kind} className="pt-4">
            <LegalEditor
              kind={kind}
              documentQuery={queryByKind[kind]}
              draftBody={draftBodyByKind[kind] ?? queryByKind[kind].data?.draft?.bodyMarkdown ?? ""}
              onDraftBodyChange={(next) => setDraftBodyByKind((prev) => ({ ...prev, [kind]: next }))}
            />
          </TabsContent>
        ))}
      </Tabs>
    </main>
  );
}
