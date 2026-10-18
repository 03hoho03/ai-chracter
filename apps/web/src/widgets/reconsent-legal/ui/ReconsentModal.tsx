import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  CONSENT_UNIT_LABEL,
  consentedVersionsFor,
  LEGAL_DOCUMENT_LABEL,
  type LegalConsentKind,
  type LegalConsentUnit,
  pendingConsentDocuments,
  pendingConsentUnits,
  useLegalChangesQuery,
  useLegalConsentMutation,
  useLegalDocumentQuery,
} from "@/entities/legal";
import { type MeResponse, sessionKeys, useSessionQuery } from "@/entities/session";
import { WithdrawAccountDialog } from "@/features/withdraw-account";

import { ReconsentDocumentSection } from "./ReconsentDocumentSection";

/** 이 모달은 닫을 수 없다 — X 버튼(`showCloseButton={false}`)·ESC·바깥 클릭을 전부 막고 `onOpenChange` 도 두지 않는다.
 * "나중에"를 두면 "계속 이용하려면 동의하라"는 문구와 달리 실제로는 계속 이용하게 둬 동작과 어긋나고, 국외이전 동의는 법정
 * 요건이라 미룰 수 없다. 출구는 동의 또는 탈퇴 둘뿐이고, 열림 여부는 세션의 동의 단위별 재동의 플래그로만 정해진다
 * (다른 요청이 재동의 403 을 받으면 전역에서 세션을 다시 불러 이 모달이 다시 뜬다). */
export function ReconsentModal() {
  const session = useSessionQuery().data;
  const pendingUnits = session === undefined ? [] : pendingConsentUnits(session);

  return (
    <Dialog open={pendingUnits.length > 0}>
      <DialogContent
        showCloseButton={false}
        onEscapeKeyDown={(event) => event.preventDefault()}
        onPointerDownOutside={(event) => event.preventDefault()}
        // 열릴 때 첫 포커스 요소(Tab 정지인 본문)로 가면 본문 전체에 포커스 테두리가 켜진 채 뜬다. 대화상자 자체에 포커스를
        // 두면 테두리 없이 열리고, 다음 Tab 이 본문부터 시작한다.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus();
        }}
        className="sm:max-w-lg"
      >
        {session !== undefined && (
          <ReconsentContent pendingUnits={pendingUnits} consentedVersions={session.legalConsentVersions} />
        )}
      </DialogContent>
    </Dialog>
  );
}

type ReconsentContentProps = {
  pendingUnits: LegalConsentUnit[];
  consentedVersions: MeResponse["legalConsentVersions"];
};

type CheckedUnits = { target: string; units: LegalConsentUnit[] };

const NO_CHECKED_UNITS: CheckedUnits = { target: "", units: [] };

/** `DialogContent` 안에 둬서 모달이 닫히면(동의 성공 → 세션 플래그 꺼짐) 체크 상태가 함께 사라진다. 상주하는 바깥 컴포넌트가
 * 체크를 쥐면, 탭을 띄워 둔 채 다음 판이 시행돼 모달이 다시 뜰 때 이미 체크된 채로 나온다. */
function ReconsentContent({ pendingUnits, consentedVersions }: ReconsentContentProps) {
  const queryClient = useQueryClient();
  const consentMutation = useLegalConsentMutation();
  const [isConsenting, setIsConsenting] = useState(false);
  const [checked, setChecked] = useState<CheckedUnits>(NO_CHECKED_UNITS);

  const documents = pendingConsentDocuments(pendingUnits);
  // 훅은 문서 수와 무관하게 늘 넷을 부른다(Rules of Hooks) — `enabled` 로 실제 조회 여부만 가른다.
  const docQueryByKind = {
    terms: useLegalDocumentQuery("terms", documents.includes("terms")),
    privacy: useLegalDocumentQuery("privacy", documents.includes("privacy")),
  } satisfies Record<LegalConsentKind, unknown>;
  const changesQueryByKind = {
    terms: useLegalChangesQuery("terms", documents.includes("terms")),
    privacy: useLegalChangesQuery("privacy", documents.includes("privacy")),
  } satisfies Record<LegalConsentKind, unknown>;

  // 전문을 받기 전에는 동의할 대상을 보여 준 것이 아니므로 체크도 동의도 막는다. 변경 안내는 보조라 기다리지 않는다 —
  // 안내를 못 받아도 전문은 펼쳐 볼 수 있다.
  const areDocumentsLoaded = documents.every((kind) => docQueryByKind[kind].data !== undefined);
  // 체크는 "이 단위들을, 이 판에" 한 것이다. 열린 채 대상이 바뀌면(다른 단위가 걸리거나 다음 판이 시행되면) 지난 체크를
  // 새 대상에 옮기지 않는다.
  const target = [...pendingUnits, ...documents.map((kind) => docQueryByKind[kind].data?.version ?? "")].join("|");
  const checkedUnits = checked.target === target ? checked.units : [];
  const areAllUnitsChecked = pendingUnits.every((unit) => checkedUnits.includes(unit));
  const canConsent = areDocumentsLoaded && areAllUnitsChecked && !isConsenting;

  function handleCheckedChange(unit: LegalConsentUnit, isChecked: boolean) {
    const others = checkedUnits.filter((checkedUnit) => checkedUnit !== unit);
    setChecked({ target, units: isChecked ? [...others, unit] : others });
  }

  function handleConsentClick() {
    if (!canConsent) return;
    void handleConsent();
  }

  async function handleConsent() {
    setIsConsenting(true);
    try {
      await consentMutation.mutateAsync({ consents: pendingUnits });
      // 세션을 다시 받는 동안 모달이 아직 떠 있다. 그 사이 다른 판이 걸려 모달이 그대로 남더라도 방금 한 체크가 새 대상에
      // 남지 않게 먼저 비운다.
      setChecked(NO_CHECKED_UNITS);
      await queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    } catch {
      toast.error("동의 처리에 실패했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsConsenting(false);
    }
  }

  return (
    <>
      {/* 본문이 스크롤하는 대화상자의 헤더는 닫기 X 자리로 오른쪽 32px 을 비워 두는데, 이 모달에는 X 가 없어 그 자리를
          돌려받는다(320px 에서 제목이 한 줄 덜 접힌다). 같은 변형 선택자로 덮어야 특이도에서 지지 않는다. */}
      <DialogHeader className="group-has-data-[slot=dialog-body]/dialog-content:pr-0">
        <DialogTitle className="break-keep">
          {documents.map((kind) => LEGAL_DOCUMENT_LABEL[kind]).join(" · ")} 개정 안내
        </DialogTitle>
        <DialogDescription>
          마지막으로 동의하신 뒤 바뀐 내용을 확인하고 동의해주세요. 동의하거나 탈퇴하기 전까지 닫히지 않아요.
        </DialogDescription>
      </DialogHeader>

      {/* 본문 전체가 Tab 정지다 — 변경 안내만 길게 이어지고 그 안에 포커스 요소가 없는 구간이 있어, 키보드로 내려 읽을 길을
          남긴다. */}
      <DialogBody scrollLabel="개정 내용" className="flex flex-col gap-4">
        {documents.map((kind) => (
          <ReconsentDocumentSection
            key={kind}
            kind={kind}
            docQuery={docQueryByKind[kind]}
            changesQuery={changesQueryByKind[kind]}
            consentedVersions={consentedVersionsFor(kind, pendingUnits, consentedVersions)}
          />
        ))}
      </DialogBody>

      {/* 체크와 버튼은 스크롤 밖 바닥 띠에 둔다 — 전문을 펼쳐 수만 자가 되어도 동의할 자리는 늘 보인다. */}
      <DialogFooter className="gap-4 sm:flex-col sm:justify-start">
        <fieldset className="flex flex-col gap-3">
          <legend className="sr-only">다시 받는 동의</legend>
          {pendingUnits.map((unit) => (
            <label key={unit} className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={checkedUnits.includes(unit)}
                disabled={!areDocumentsLoaded}
                onCheckedChange={(isChecked) => handleCheckedChange(unit, isChecked === true)}
              />
              {CONSENT_UNIT_LABEL[unit]}
            </label>
          ))}
        </fieldset>
        {/* 좁은 화면에서도 두 버튼을 한 줄에 둔다 — 체크가 셋까지 쌓이는 띠라, 세로로 쌓으면 320×568 에서 본문이 읽을 수 없게
            줄어든다. 탈퇴 버튼은 글자 폭 그대로 두고 남은 폭을 동의가 갖는다. */}
        <div className="flex gap-2 sm:justify-end">
          {/* 동의하지 않는 회원의 출구는 탈퇴다. 확인 대화상자가 이 모달 위에 겹쳐 뜬다. */}
          <WithdrawAccountDialog label="동의하지 않고 탈퇴" isBehindReconsent />
          {/* 로딩 중 `disabled` 는 브라우저가 즉시 blur 해 포커스를 <body> 로 떨어뜨린다. 이 모달은 ESC 를 막아 키보드로
              돌아올 길이 Tab 하나뿐이라 `aria-disabled` + 핸들러 첫 줄 return 으로 막는다. */}
          <Button
            type="button"
            aria-disabled={!canConsent}
            className="flex-1 aria-disabled:pointer-events-none aria-disabled:opacity-65 sm:flex-none"
            onClick={handleConsentClick}
          >
            {isConsenting ? "처리 중..." : "동의"}
          </Button>
        </div>
      </DialogFooter>
    </>
  );
}
