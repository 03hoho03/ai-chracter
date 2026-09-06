import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useEffect, useState } from "react";

import { LEGAL_KIND_LABELS, type LegalKind } from "../api/keys";
import { useLegalDocumentQuery } from "../api/useLegalDocumentQuery";
import { LegalEditor } from "./LegalEditor";

const LEGAL_KINDS: LegalKind[] = ["terms", "privacy"];

function isLegalKind(value: string): value is LegalKind {
  return value === "terms" || value === "privacy";
}

/** 두 탭의 데이터는 항상 함께 불러온다(문서 2개뿐이라 비용이 작다) — 탭을 바꿔도 안 보이는
 * `TabsContent`가 언마운트될 뿐, 로컬 편집 버퍼(`draftBodyByKind`)는 이 컴포넌트에 있어 살아남는다.
 * 그래서 "저장 안 한 편집 내용이 있는데 탭을 바꾸면 잃는다"는 별도 경고 없이 자연히 해결된다. */
export function LegalPage() {
  const [activeKind, setActiveKind] = useState<LegalKind>("terms");
  const [draftBodyByKind, setDraftBodyByKind] = useState<Partial<Record<LegalKind, string>>>({});

  const termsQuery = useLegalDocumentQuery("terms");
  const privacyQuery = useLegalDocumentQuery("privacy");

  // 서버 초안은 kind당 한 번만 로컬 버퍼로 옮긴다 — 이후엔 사용자가 타이핑한 값이 우선이다.
  useEffect(() => {
    if (termsQuery.data && draftBodyByKind.terms === undefined) {
      setDraftBodyByKind((prev) => ({ ...prev, terms: termsQuery.data.draft?.bodyMarkdown ?? "" }));
    }
  }, [termsQuery.data, draftBodyByKind.terms]);

  useEffect(() => {
    if (privacyQuery.data && draftBodyByKind.privacy === undefined) {
      setDraftBodyByKind((prev) => ({ ...prev, privacy: privacyQuery.data.draft?.bodyMarkdown ?? "" }));
    }
  }, [privacyQuery.data, draftBodyByKind.privacy]);

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
              document={queryByKind[kind].data}
              isPending={queryByKind[kind].isPending}
              isError={queryByKind[kind].isError}
              draftBody={draftBodyByKind[kind] ?? ""}
              onDraftBodyChange={(next) => setDraftBodyByKind((prev) => ({ ...prev, [kind]: next }))}
            />
          </TabsContent>
        ))}
      </Tabs>
    </main>
  );
}
