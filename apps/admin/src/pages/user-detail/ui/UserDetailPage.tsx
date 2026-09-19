import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import {
  ACTION_TYPE_LABELS,
  CHAT_VIEW_REASON_CATEGORY_LABELS,
  CLOVER_KIND_LABELS,
  SIGNUP_METHOD_LABELS,
  useCloverLedgerQuery,
  useUserDetailQuery,
} from "@/entities/admin-user";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS } from "@/entities/report";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { UserActionPanel } from "./UserActionPanel";

// 문장 속 링크는 `font-medium text-primary hover:underline`이 저장소 관용구다(MyPagePage 동형).
const INLINE_LINK_CLASS = "font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none";

type UserDetailPageProps = {
  userId: string;
};

export function UserDetailPage({ userId }: UserDetailPageProps) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/users">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">유저 상세</h1>

      <UserDetailBody userId={userId} />
    </main>
  );
}

type UserDetailBodyProps = {
  userId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function UserDetailBody({ userId }: UserDetailBodyProps) {
  const userDetailQuery = useUserDetailQuery(userId);

  if (userDetailQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (userDetailQuery.isError) {
    return <p className="text-sm text-destructive-text">유저 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  return (
    <>
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <span>{SIGNUP_METHOD_LABELS[userDetailQuery.data.signupMethod]}</span>
            <span aria-hidden>·</span>
            <span>{userDetailQuery.data.suspendedAt ? "정지" : "정상"}</span>
            {/* limit-goal-prompt.md RL-19 — 면제는 상세에만 있는 플래그라 여기서만 읽을 수 있다.
             * 정지 여부와 달리 "아님"일 때는 아무것도 붙이지 않는다(기본값이라 상태 줄이 길어지기만 한다). */}
            {userDetailQuery.data.rateLimitExempt && (
              <>
                <span aria-hidden>·</span>
                <span>레이트리밋 면제</span>
              </>
            )}
          </div>
          <p className="text-lg font-semibold text-foreground">{userDetailQuery.data.nickname}</p>
          <p className="text-sm text-muted-foreground">{userDetailQuery.data.email}</p>
          <p className="text-xs text-muted-foreground">
            {formatDateTime(userDetailQuery.data.createdAt)} 가입
          </p>
        </div>

        {userDetailQuery.data.bio && (
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-medium text-foreground">자기소개</h3>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{userDetailQuery.data.bio}</p>
          </div>
        )}

        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">이메일 인증</dt>
            <dd className="text-foreground">{formatDateTime(userDetailQuery.data.emailVerifiedAt)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">최근 활동</dt>
            <dd className="text-foreground">{formatDateTime(userDetailQuery.data.lastActiveAt)}</dd>
          </div>
        </dl>

        {/* 클로버 잔액을 여기 넣는 이유: 작품·채팅방·메시지와 같은 "이 유저의 현재 수치"이고,
         * 조치 패널의 지급·회수가 바로 이 숫자를 움직인다. 별도 섹션으로 떼면 조치와 그 대상이
         * 화면에서 멀어진다(clover-techspec.md §6). */}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">작품수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(userDetailQuery.data.contentCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">채팅방수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(userDetailQuery.data.chatRoomCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">메시지수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(userDetailQuery.data.messageCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">클로버</dt>
            <dd className="tabular-nums text-foreground">{formatCount(userDetailQuery.data.cloverBalance)}</dd>
          </div>
        </dl>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">신고 이력</h2>
        {userDetailQuery.data.reports.length === 0 ? (
          <p className="text-sm text-muted-foreground">신고 이력이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>대상 작품</TableHead>
                  <TableHead>사유</TableHead>
                  <TableHead>처리상태</TableHead>
                  <TableHead>신고일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {userDetailQuery.data.reports.map((report) => (
                  <TableRow key={report.id}>
                    <TableCell>
                      <Link to="/reports/$reportId" params={{ reportId: report.id }} className={INLINE_LINK_CLASS}>
                        {report.contentName || "(이름 없음)"}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {REPORT_REASON_LABELS[report.reasonCategory]}
                    </TableCell>
                    <TableCell>{REPORT_STATUS_LABELS[report.status]}</TableCell>
                    <TableCell>{formatDateTime(report.createdAt)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">조치 이력</h2>
        {userDetailQuery.data.actionLogs.length === 0 ? (
          <p className="text-sm text-muted-foreground">조치 이력이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>조치</TableHead>
                  <TableHead>대상 작품</TableHead>
                  <TableHead>사유</TableHead>
                  <TableHead>코멘트</TableHead>
                  <TableHead>조치일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {userDetailQuery.data.actionLogs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell>{ACTION_TYPE_LABELS[log.actionType] ?? log.actionType}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {log.targetContentId ? (
                        <Link
                          to="/contents/$contentId"
                          params={{ contentId: log.targetContentId }}
                          className={INLINE_LINK_CLASS}
                        >
                          {log.contentName || "(이름 없음)"}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{reasonCategoryLabel(log.reasonCategory)}</TableCell>
                    <TableCell className="text-muted-foreground">{log.reasonText || "-"}</TableCell>
                    <TableCell>{formatDateTime(log.createdAt)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <CloverLedgerSection userId={userId} />

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">채팅방</h2>
        {userDetailQuery.data.chatRooms.length === 0 ? (
          <p className="text-sm text-muted-foreground">채팅방이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>작품</TableHead>
                  <TableHead>방 이름</TableHead>
                  <TableHead className="text-right">턴수</TableHead>
                  <TableHead className="text-right">메시지수</TableHead>
                  <TableHead>최근 대화</TableHead>
                  <TableHead>생성일시</TableHead>
                  <TableHead>채팅 내용</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {userDetailQuery.data.chatRooms.map((chatRoom) => (
                  <TableRow key={chatRoom.id}>
                    <TableCell>
                      <Link
                        to="/contents/$contentId"
                        params={{ contentId: chatRoom.contentId }}
                        className={INLINE_LINK_CLASS}
                      >
                        {chatRoom.contentName || "(이름 없음)"}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{chatRoom.name || "-"}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCount(chatRoom.turnCount)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCount(chatRoom.messageCount)}</TableCell>
                    <TableCell>{formatDateTime(chatRoom.lastMessageAt)}</TableCell>
                    <TableCell>{formatDateTime(chatRoom.createdAt)}</TableCell>
                    <TableCell>
                      <Link
                        to="/users/$userId/chats/$roomId"
                        params={{ userId, roomId: chatRoom.id }}
                        className={INLINE_LINK_CLASS}
                      >
                        열람
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      {/* image-monitoring-goal-prompt.md IM-1 — 같은 그리드를 두 벌 유지하지 않으려 링크만 둔다.
       * 유저 상세 응답(AdminUserDetailResponse)에 생성 이미지 건수 필드가 없어(BE는 이 런에서
       * 건드리지 않는다) "N건"은 못 붙이고 목적지만 알린다. */}
      <section className="flex items-center justify-between rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">생성 이미지</h2>
        <Link to="/users/$userId/image-generations" params={{ userId }} className={INLINE_LINK_CLASS}>
          생성 이미지 열람 →
        </Link>
      </section>

      <UserActionPanel
        userId={userDetailQuery.data.id}
        isSuspended={userDetailQuery.data.suspendedAt !== null}
        isRateLimitExempt={userDetailQuery.data.rateLimitExempt}
        restrictableContentCount={userDetailQuery.data.restrictableContentCount}
      />
    </>
  );
}

type CloverLedgerSectionProps = {
  userId: string;
};

/** 원장은 상세 응답이 아니라 별도 라우트다(clover-techspec.md §4-5) — 상세가 이미 목록 셋을
 * 싣고 있어 네 번째를 얹으면 한 요청이 무거워진다. 그래서 로딩·에러도 이 섹션이 따로 진다.
 *
 * 🔴 **첫 페이지 20건만** 쓴다(사용자 결정 — 전용 목록 페이지는 만들지 않는다). 그보다 오래된
 * 내역이 필요한 일은 아직 없고, 필요해지면 그때 `page`를 올리는 화면만 더하면 된다. */
function CloverLedgerSection({ userId }: CloverLedgerSectionProps) {
  const ledgerQuery = useCloverLedgerQuery(userId);

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">클로버 원장</h2>
        {ledgerQuery.isSuccess && ledgerQuery.data.totalCount > ledgerQuery.data.items.length && (
          <p className="text-xs text-muted-foreground">
            최근 {formatCount(ledgerQuery.data.items.length)}건 / 전체 {formatCount(ledgerQuery.data.totalCount)}건
          </p>
        )}
      </div>

      {ledgerQuery.isPending && <div className="h-24 animate-pulse rounded-lg bg-muted" />}

      {ledgerQuery.isError && (
        <p className="text-sm text-destructive-text">원장을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {ledgerQuery.isSuccess &&
        (ledgerQuery.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">클로버가 오간 기록이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>종류</TableHead>
                  <TableHead className="text-right">증감</TableHead>
                  <TableHead className="text-right">이후 잔액</TableHead>
                  <TableHead>일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ledgerQuery.data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{CLOVER_KIND_LABELS[item.kind] ?? item.kind}</TableCell>
                    {/* 부호를 숫자에 붙여 방향을 읽게 한다 — 색으로 가르지 않는 것은 이 앱의
                     * 규칙이다(유채색은 위험 액션에만, PRODUCT.md). 차감이 위험은 아니다. */}
                    <TableCell className="text-right tabular-nums">{formatSignedCount(item.amount)}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {formatCount(item.balanceAfter)}
                    </TableCell>
                    <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))}
    </section>
  );
}

/** 원장은 증감이라 부호가 값의 일부다 — `formatCount`는 음수에 `-`만 붙이므로 지급 쪽에 `+`를
 * 손으로 붙인다. 0은 원장에 들어오지 않는다(BE가 `amount=0`을 거부한다). */
function formatSignedCount(amount: number) {
  return amount > 0 ? `+${formatCount(amount)}` : formatCount(amount);
}

/** `AdminUserActionLogItem.reasonCategory`는 enum이 아니라 plain `string | null`이다 — 작품 직접
 * 조치 로그(신고 사유 5종, REPORT_REASON_LABELS)와 채팅 열람 로그(별도 사유 4종,
 * CHAT_VIEW_REASON_CATEGORY_LABELS)가 같은 테이블을 써서 두 사유 체계가 섞여 들어온다. `other`는
 * 두 집합 모두에 있지만 한글 라벨이 둘 다 "기타"로 같으므로(entities/report, entities/admin-user
 * 각 model/labels.ts 확인) 스프레드 순서와 무관하게 값이 동일하다 — 합쳐도 의미가 바뀌지 않는다.
 * `Record<string, string>`이라 `??` 폴백으로 모르는 값은 원문 그대로 보여준다(ACTION_TYPE_LABELS와
 * 동일한 관례). */
const REASON_CATEGORY_LABELS_ALL: Record<string, string> = {
  ...REPORT_REASON_LABELS,
  ...CHAT_VIEW_REASON_CATEGORY_LABELS,
};

function reasonCategoryLabel(reasonCategory: string | null) {
  if (!reasonCategory) return "-";
  return REASON_CATEGORY_LABELS_ALL[reasonCategory] ?? reasonCategory;
}
