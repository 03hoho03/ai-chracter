import { useId, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { useChatRoomQuery } from "@/entities/chat-room";
import { usePersonasQuery, type Persona, type PersonaList } from "@/entities/persona";
import { CreatePersonaForm } from "@/features/manage-persona";
import { RoomPersonaPicker, useSetRoomPersonaMutation } from "@/features/select-room-persona";

type RoomPersonaModalProps = {
  roomId: string;
};

/** 채팅방 안의 대화 프로필 선택(+ 간단한 새로 만들기).
 *
 * **모달인 이유**: `ChatMoreNav`의 다른 항목(플레이가이드·업데이트 정보·시작설정 변경·엔딩
 * 컬렉션·이미지 보관함)이 전부 "패널을 닫고 react-call 모달을 연다"이고, 그 목록과 핸들러를 lg 이상
 * 인라인 사이드바와 lg 미만 드롭업 시트가 공유한다. 이 항목만 패널 안에서 펼치면 ① 시트 안에 폼이 들어가
 * 390px 드롭업에서 키보드가 올라올 때 스크롤 영역이 두 겹이 되고 ② 두 패널 컨테이너에 같은 분기를 넣어야
 * 한다. 모달이면 두 레이아웃이 같은 코드 한 벌을 쓴다.
 *
 * 새로 만들기는 모달 안 **뷰 전환**이다(모달 위 모달을 쌓지 않는다). 만든 즉시 그 방에 선택한다 — 생성과
 * 방 선택은 두 feature라(feature끼리 import 금지) 이 위젯이 조합한다. 생성 폼의 "기본으로 지정" 규칙은
 * 관리 페이지와 같은 `CreatePersonaForm` 하나다. */
export const RoomPersonaModal = createCallable<RoomPersonaModalProps, void>(({ call, roomId }) => {
  const [view, setView] = useState<"select" | "create">("select");
  const room = useChatRoomQuery(roomId).data;
  const personasQuery = usePersonasQuery();
  const setRoomPersonaMutation = useSetRoomPersonaMutation(roomId);

  // 폼이 이 Promise를 기다린다 — 방 적용 PUT이 끝날 때까지 "저장 중"으로 남아 재제출(프로필 중복 생성)을
  // 막는다. 적용 실패는 여기서 삼킨다 — 폼으로 던지면 루트 에러가 되어 폼에 머문다.
  async function handleCreated(persona: Persona) {
    try {
      await setRoomPersonaMutation.mutateAsync(persona.id);
    } catch {
      // 프로필은 이미 만들어졌다 — 폼으로 되돌리면 같은 것을 또 만들게 되므로 목록으로 보낸다.
      toast.error("프로필은 만들었지만 이 대화방에 적용하지 못했어요. 목록에서 다시 골라주세요.");
      setView("select");
      return;
    }
    toast.success("새 프로필을 만들고 이 대화방에 적용했어요. 다음 대화부터 반영돼요.");
    call.end();
  }

  const personaList = personasQuery.data;
  const isCreateView = view === "create" && personaList !== undefined;

  // 세 상태(불러오는 중·실패·목록)는 배타적이다 — 렌더 전에 한 갈래로 정한다(ChatRoomView `errorNotice` 선례).
  let body: ReactNode;
  if (personasQuery.isPending) {
    body = <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>;
  } else if (!personaList) {
    body = (
      <div className="flex flex-col items-center gap-3 py-6">
        <p className="text-sm break-keep text-muted-foreground">대화 프로필을 불러오지 못했어요.</p>
        <Button type="button" variant="outline" onClick={() => void personasQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  } else if (isCreateView) {
    body = (
      <CreatePersonaForm
        defaultPersonaId={personaList.defaultPersonaId}
        onCreated={handleCreated}
        onCancel={() => setView("select")}
      />
    );
  } else {
    body = (
      <RoomPersonaSelectView
        roomId={roomId}
        currentPersonaId={room?.personaId}
        personaList={personaList}
        onChanged={() => call.end()}
        onCreate={() => setView("create")}
        onNavigateAway={() => call.end()}
      />
    );
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
      {/* 내용이 길어질 수 있어(프로필 10개 + 폼) 최대 높이와 내부 스크롤을 호출부에서 준다(packages/ui/CLAUDE.md). */}
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isCreateView ? "새 대화 프로필" : "대화 프로필"}</DialogTitle>
          <DialogDescription className="break-keep">
            {isCreateView
              ? "만들면 바로 이 대화방에 적용돼요."
              : "이 대화방에서 캐릭터가 알게 될 '나'예요. 바꾸면 다음 대화부터 반영되고, 지난 대화는 그대로예요."}
          </DialogDescription>
        </DialogHeader>

        {body}
      </DialogContent>
    </Dialog>
  );
});

type RoomPersonaSelectViewProps = {
  roomId: string;
  currentPersonaId: string | undefined;
  personaList: PersonaList;
  onChanged: () => void;
  onCreate: () => void;
  onNavigateAway: () => void;
};

function RoomPersonaSelectView({
  roomId,
  currentPersonaId,
  personaList,
  onChanged,
  onCreate,
  onNavigateAway,
}: RoomPersonaSelectViewProps) {
  const limitHintId = useId();
  const isAtLimit = personaList.items.length >= personaList.maxCount;

  return (
    <div className="flex flex-col gap-4">
      <RoomPersonaPicker
        roomId={roomId}
        currentPersonaId={currentPersonaId}
        personaList={personaList}
        onChanged={onChanged}
      />

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <Button
            type="button"
            variant="outline"
            aria-disabled={isAtLimit}
            aria-describedby={isAtLimit ? limitHintId : undefined}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (isAtLimit) return;
              onCreate();
            }}
          >
            <Plus aria-hidden />
            새로 만들기
          </Button>
          <Link
            to="/personas"
            onClick={onNavigateAway}
            className="text-sm font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline"
          >
            프로필 관리
          </Link>
        </div>
        {isAtLimit && (
          <p id={limitHintId} className="text-xs break-keep text-muted-foreground">
            대화 프로필은 최대 {personaList.maxCount}개까지 만들 수 있어요. 프로필 관리에서 하나를 지우면 새로
            만들 수 있어요.
          </p>
        )}
      </div>
    </div>
  );
}
