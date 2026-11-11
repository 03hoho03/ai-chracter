import type { ReactNode } from "react";

import type { HostedFailure } from "@/shared/api/service/hostedFailure";
import { CONTRACT_VERSION } from "@/shared/api/service/hostedRuns";
import { assertNever } from "@/shared/lib/assertNever";
import { Button, buttonClassName } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";

/** Access 의 같은 출처 고정 경로 — 다른 Google 계정으로 들어가려면 Access 세션부터 끝내야 한다. */
const ACCESS_LOGOUT_PATH = "/cdn-cgi/access/logout";

type HostedFailureNoticeProps = {
  failure: HostedFailure;
  /** 무엇을 받지 못했나 — 서비스가 거부했을 때 제목이 갈린다. */
  subject: "list" | "run";
  onRetry: () => void;
  /** 런 목록으로 돌아가는 링크(상세에서만). 다시 받아도 같은 실패(없는 런·읽지 못하는 판)의 행동이다. */
  backToList?: ReactNode;
};

/**
 * 호스팅 화면이 서비스에서 런 목록·런을 받지 못했을 때 본문 자리 안내. 목록·상세가 같은 안내를 쓴다. 무엇이 일어났고 무엇을 하면
 * 되는지를 적는다 — 세션이 끝났으면 새로고침(로그인 화면을 거친다), 서비스가 까닭을 말했으면 그 문장 그대로.
 */
export function HostedFailureNotice({ failure, subject, onRetry, backToList }: HostedFailureNoticeProps) {
  const retry = (
    <Button variant="primary" onClick={onRetry}>
      다시 시도
    </Button>
  );

  switch (failure.kind) {
    case "session":
      return (
        <Notice title="서비스에 닿지 못했다" action={<ReloadButton />}>
          <p>
            로그인이 끝났거나(Access 로그인은 정해진 시간이 지나면 끝난다) 네트워크가 끊겼다. 새로고침하면 로그인 화면을 거쳐 다시
            연다.
          </p>
          {failure.accessBlocked && <p>Access 가 이 요청을 막았다 — 허용된 Google 계정으로 로그인했는지 본다.</p>}
          <p className="font-mono text-data text-ink-muted">{failure.code}</p>
        </Notice>
      );
    case "notAllowed":
      return (
        <Notice
          title="이 계정으로는 런 목록을 볼 수 없다"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <ReloadButton />
              <a href={ACCESS_LOGOUT_PATH} className={buttonClassName("ghost")}>
                로그아웃
              </a>
            </div>
          }
        >
          <p>
            서비스가 이 로그인을 받지 않았다 — 허용된 Google 계정인지 본다. 다른 계정으로 들어가려면 로그아웃한 뒤 다시 연다.
          </p>
        </Notice>
      );
    case "service":
      return (
        <Notice title={subject === "list" ? "런 목록을 받지 못했다" : "런을 받지 못했다"} action={retry}>
          <p className="text-ink">{failure.detail}</p>
          <p className="font-mono text-data text-ink-muted">{failure.reason}</p>
        </Notice>
      );
    case "unavailable":
      return (
        <Notice title="서비스가 지금 응답하지 않는다" action={retry}>
          <p>서비스나 그 앞단이 내려가 있거나 다시 뜨는 중이다. 잠시 뒤 다시 받는다.</p>
          <p className="font-mono text-data text-ink-muted">상태 {failure.status}</p>
        </Notice>
      );
    case "badResponse":
      return (
        <Notice title="서비스 응답이 이 웹이 아는 꼴이 아니다" action={retry}>
          <p>웹과 서비스가 다른 커밋에서 나왔을 수 있다 — 서비스 이미지를 웹과 같은 커밋으로 다시 만든다.</p>
        </Notice>
      );
    case "notFound":
      return (
        <Notice title="이 런이 서비스에 없다" action={backToList}>
          <p>누가 지웠거나 주소의 런 id 가 옛 것이다. 목록을 다시 받아 본다.</p>
        </Notice>
      );
    case "unsupportedContract":
      return (
        <Notice title="이 판은 이 웹이 읽지 못한다" action={backToList}>
          <p>{contractText(failure.found)}</p>
        </Notice>
      );
    case "serverless":
      return (
        <Notice title="측정 서버가 있어야 하는 동작이다" action={backToList}>
          <p>호스팅 화면은 서비스에 올라온 판만 읽고 측정 서버에는 닿지 않는다.</p>
        </Notice>
      );
    default:
      return assertNever(failure);
  }
}

/** 세션이 끝났으면 다시 받아도 같다 — 문서를 새로 열어야 Access 가 로그인 화면으로 보낸다. */
function ReloadButton() {
  return (
    <Button variant="primary" onClick={() => window.location.reload()}>
      새로고침
    </Button>
  );
}

/** 계약 판이 이 웹보다 새면 웹을 다시 배포하고, 옛 판이면 원본 런을 다시 올린다 — 고칠 쪽이 다르다. */
function contractText(found: number): string {
  if (found > CONTRACT_VERSION) {
    return `계약 판 ${found} 로 올라온 묶음이다. 이 웹은 판 ${CONTRACT_VERSION} 을 읽는다 — 서비스를 측정 서버와 같은 커밋의 웹으로 다시 배포하면 열린다.`;
  }
  return `이 웹보다 옛 측정 서버가 만든 묶음이다(계약 판 ${found}). 원본 런을 지금의 측정 서버로 다시 올리면 새 판으로 열린다.`;
}
