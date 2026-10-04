import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useState } from "react";

import { PageContainer } from "@/shared/ui/PageContainer";
import { UnsavedChangesGuard } from "@/shared/ui/UnsavedChangesGuard";

import { isLegalKind, LEGAL_KIND_LABELS, LEGAL_KINDS, type LegalKind } from "../model/legalKind";
import { useLegalDocumentQuery } from "../api/useLegalDocumentQuery";
import { LegalEditor } from "./LegalEditor";

/** 두 탭의 데이터는 항상 함께 불러온다(문서 2개뿐이라 비용이 작다) — 탭을 바꿔도 안 보이는
 * `TabsContent`가 언마운트될 뿐, 로컬 편집 버퍼(`draftBodyByKind`)는 이 컴포넌트에 있어 살아남는다.
 * 그래서 "저장 안 한 편집 내용이 있는데 탭을 바꾸면 잃는다"는 별도 경고 없이 자연히 해결된다. 다른 화면으로 떠날 때는
 * 버퍼가 사라지므로 두 문서 중 하나라도 저장하지 않은 변경이 있으면 확인을 받는다. */
export function LegalPage() {
  const [activeKind, setActiveKind] = useState<LegalKind>("terms");
  // 사용자가 아직 손대지 않은 kind는 키가 없다 — 그때는 렌더 중에 서버 초안을 그대로 읽는다.
  const [draftBodyByKind, setDraftBodyByKind] = useState<Partial<Record<LegalKind, string>>>({});

  const termsQuery = useLegalDocumentQuery("terms");
  const privacyQuery = useLegalDocumentQuery("privacy");
  const queryByKind = { terms: termsQuery, privacy: privacyQuery };
  const savedDraftBodyOf = (kind: LegalKind) => queryByKind[kind].data?.draft?.bodyMarkdown ?? "";
  const draftBodyOf = (kind: LegalKind) => draftBodyByKind[kind] ?? savedDraftBodyOf(kind);
  // 편집기의 "저장하지 않은 변경사항" 표시와 같은 비교다(버퍼 ≠ 저장된 초안). 저장 응답이 캐시를 바로 채워 저장
  // 직후 거짓이 되고, 게시는 초안을 바꾸지 않아 게시 직후에도 그대로 거짓이다.
  const hasUnsavedDraft = LEGAL_KINDS.some((kind) => draftBodyOf(kind) !== savedDraftBodyOf(kind));

  return (
    <PageContainer>
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
              draftBody={draftBodyOf(kind)}
              onDraftBodyChange={(next) => setDraftBodyByKind((prev) => ({ ...prev, [kind]: next }))}
            />
          </TabsContent>
        ))}
      </Tabs>

      <UnsavedChangesGuard isDirty={hasUnsavedDraft} />
    </PageContainer>
  );
}
