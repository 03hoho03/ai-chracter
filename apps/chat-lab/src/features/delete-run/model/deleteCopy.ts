import type { HostedFailure } from "@/shared/api/service/hostedFailure";
import { assertNever } from "@/shared/lib/assertNever";
import { formatCount } from "@/shared/lib/formatNumber";

/**
 * 확인 대화가 런을 가리키는 말. 이야기 이름이 있으면 그 이름, 없으면 경로(고정폭), 둘 다 없으면 런 id(고정폭) — 목록 칸 꼴이 틀려
 * 이 웹이 읽지 못하는 런도 지울 수 있어야 한다.
 */
export type DeleteSubject =
  | { kind: "story"; name: string }
  | { kind: "path"; path: string }
  | { kind: "runId"; runId: string };

export type DeleteCopy = {
  title: string;
  /** 가리킨 런 뒤에 잇는 문장 — 판이 여럿이면 모두 지운다는 것을 누르기 전에 본다. */
  scope: string;
  confirmLabel: string;
  subject: DeleteSubject;
};

type DeleteCopyInput = {
  versionCount: number;
  runId: string;
  storyName?: string | null;
  path?: string;
};

/** 지우기 확인 대화의 문장. 판 수가 제목과 위험 버튼 둘 다에 들어간다 — 서비스의 지우기는 최신 판이 아니라 런의 모든 판이다. */
export function deleteCopy({ versionCount, runId, storyName, path }: DeleteCopyInput): DeleteCopy {
  const count = `판 ${formatCount(versionCount)}개`;
  const isMany = versionCount > 1;
  return {
    title: isMany ? `런을 지운다 — ${count} 모두` : `런을 지운다 — ${count}`,
    scope: isMany ? `${count}를 모두 지운다. 최신 판 하나만 지우는 것이 아니다.` : `${count}를 지운다.`,
    confirmLabel: isMany ? `${count} 모두 지우기` : `${count} 지우기`,
    subject: deleteSubject(runId, storyName, path),
  };
}

/** 지우기 직전에 다시 받은 목록에서 그 런의 판이 달라 지우지 않았을 때 대화 안에 남기는 한 줄. 판 수는 다시 받은 값이다. */
export function versionsChangedText(versionCount: number): string {
  return `그 사이 새 판이 올라왔다 — 목록을 다시 받았다. 판 ${formatCount(versionCount)}개를 다시 보고 지운다.`;
}

/**
 * 지우지 못했을 때 대화 안에 남기는 한 줄. 세션이 끝났으면 다시 로그인한 뒤 지우라고 하고, 서비스가 까닭을 말했으면 그 문장을
 * 그대로 싣는다. 없는 런(404)은 이미 지워진 것으로 정리하고 대화를 닫으므로 이 줄에 서지 않는다.
 */
export function deleteFailureText(failure: HostedFailure): string {
  switch (failure.kind) {
    case "session":
      return failure.accessBlocked
        ? "Access 가 이 요청을 막았다 — 허용된 Google 계정으로 로그인했는지 본 뒤 새로고침해 다시 지운다."
        : "로그인이 끝났을 수 있다 — 새로고침해 다시 로그인한 뒤 지운다.";
    case "service":
      return `지우지 못했다 — ${failure.detail}`;
    case "unavailable":
      return `지우지 못했다 — 서비스가 지금 응답하지 않는다(상태 ${failure.status}). 잠시 뒤 다시 지운다.`;
    case "badResponse":
      return "지우지 못했다 — 서비스 응답이 이 웹이 아는 꼴이 아니다. 웹과 서비스가 다른 커밋에서 나왔을 수 있다.";
    case "notFound":
      return "이미 지워진 런이다.";
    // 지우기 직전에 목록을 다시 받다가 404 를 받았다.
    case "notAllowed":
      return "지우지 못했다 — 서비스가 이 로그인을 받지 않았다. 허용된 Google 계정인지 본 뒤 새로고침한다.";
    // 지우기에서는 나지 않는 갈래다 — 묶음 로더·측정 서버 차단에서만 난다.
    case "serverless":
    case "unsupportedContract":
      return "지우지 못했다 — 서비스가 이 지우기를 받지 않았다.";
    default:
      return assertNever(failure);
  }
}

function deleteSubject(runId: string, storyName: string | null | undefined, path: string | undefined): DeleteSubject {
  if (storyName != null && storyName !== "") return { kind: "story", name: storyName };
  if (path !== undefined && path !== "") return { kind: "path", path };
  return { kind: "runId", runId };
}
