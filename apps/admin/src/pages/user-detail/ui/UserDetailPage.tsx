import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import {
  ACTION_TYPE_LABELS,
  CHAT_VIEW_REASON_CATEGORY_LABELS,
  CLOVER_KIND_LABELS,
  SIGNUP_METHOD_LABELS,
  useCloverLedgerQuery,
  useUserDetailQuery,
  type AdminUserDetailResponse,
} from "@/entities/admin-user";
import { CHAT_MESSAGE_REPORT_REASON_LABELS, REPORT_REASON_LABELS, REPORT_STATUS_LABELS } from "@/entities/report";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime, formatDateTimeParts } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DenseTable } from "@/shared/ui/DenseTable";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { UserActionPanel } from "./UserActionPanel";

type UserDetailPageProps = {
  userId: string;
};

// 문장 속 링크는 `font-medium text-primary hover:underline`이 저장소 관용구다(MyPagePage 동형). 글자 크기 그대로라
// 누르는 면은 `admin-hit-area`(app/styles/admin.css)가 박스를 바꾸지 않고 넓힌다.
const INLINE_LINK_CLASS =
  "admin-hit-area font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none";


/** `AdminUserActionLogItem.reasonCategory`는 enum이 아니라 plain `string | null`이다 — 작품 직접
 * 조치 로그(신고 사유, REPORT_REASON_LABELS), 채팅 열람 로그(별도 사유,
 * CHAT_VIEW_REASON_CATEGORY_LABELS), 채팅 응답 신고 처리 로그(신고 사유,
 * CHAT_MESSAGE_REPORT_REASON_LABELS)가 같은 테이블을 써서 세 사유 체계가 섞여 들어온다. 겹치는 키는
 * `other`("기타", 세 집합 모두)와 `minor_safety`("아동·청소년 관련", 작품 신고·채팅 응답 신고 둘)이고
 * 겹치는 집합끼리 한글 라벨이 같으므로(entities/report, entities/admin-user 각 model/labels.ts 확인)
 * 스프레드 순서와 무관하게 값이 동일하다 — 합쳐도 의미가 바뀌지 않는다. 겹치는 키를 새로 만들면
 * 라벨도 같게 둔다.
 * `Record<string, string>`이라 `??` 폴백으로 모르는 값은 원문 그대로 보여준다(CLOVER_KIND_LABELS와
 * 동일한 관례 — 유니언으로 강제하는 ACTION_TYPE_LABELS와는 다르다). */
const REASON_CATEGORY_LABELS_ALL: Record<string, string> = {
  ...REPORT_REASON_LABELS,
  ...CHAT_VIEW_REASON_CATEGORY_LABELS,
  ...CHAT_MESSAGE_REPORT_REASON_LABELS,
};

export function UserDetailPage({ userId }: UserDetailPageProps) {
  // 마지막으로 본 목록(필터·검색어·페이지)으로 돌아간다 — 대시보드 등 다른 입구로 들어왔어도 같다.
  const rememberedListSearch = useRememberedListSearch("/users/");
  return (
    <PageContainer>
      <PageHeader
        title="유저 상세"
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/users" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      <UserDetailBody userId={userId} />
    </PageContainer>
  );
}

type UserDetailBodyProps = {
  userId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function UserDetailBody({ userId }: UserDetailBodyProps) {
  const userDetailQuery = useUserDetailQuery(userId);
  useDocumentTitle("유저 상세", userDetailQuery.data?.nickname);

  return (
    <QueryState query={userDetailQuery} skeleton="detail" errorMessage="유저 정보를 불러오지 못했어요.">
      {(user) => (
        <DetailLayout
          actions={{
            title: "조치",
            triggerLabel: "조치하기",
            summary: userStatusSummary(user),
            render: (host) => (
              <UserActionPanel
                userId={user.id}
                isSuspended={user.suspendedAt !== null}
                isRateLimitExempt={user.rateLimitExempt}
                isBeta={user.betaJoinedAt !== null}
                isNovelizeGranted={user.novelizeGrantedAt !== null}
                restrictableContentCount={user.restrictableContentCount}
                restorableContentCount={user.restorableContentCount}
                onSuccess={host.onDone}
              />
            ),
          }}
        >
          <UserDetailSections userId={userId} user={user} />
        </DetailLayout>
      )}
    </QueryState>
  );
}

type UserDetailSectionsProps = {
  userId: string;
  user: AdminUserDetailResponse;
};

function UserDetailSections({ userId, user }: UserDetailSectionsProps) {
  return (
    <>
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <span>{SIGNUP_METHOD_LABELS[user.signupMethod]}</span>
            <span aria-hidden>·</span>
            <span>{user.suspendedAt ? "정지" : "정상"}</span>
            {/* 면제는 상세에만 있는 플래그라 여기서만 읽을 수 있다.
             * 정지 여부와 달리 "아님"일 때는 아무것도 붙이지 않는다(기본값이라 상태 줄이 길어지기만 한다). */}
            {user.rateLimitExempt && (
              <>
                <span aria-hidden>·</span>
                <span>레이트리밋 면제</span>
              </>
            )}
            {/* 베타도 "아님"이 기본값이라 같은 이유로 지정된 경우만 붙인다. 지정 시각은 아래 `dl`에 둔다. */}
            {!!user.betaJoinedAt && (
              <>
                <span aria-hidden>·</span>
                <span>베타 참가</span>
              </>
            )}
          </div>
          <p className="break-keep text-lg font-semibold text-foreground wrap-anywhere">{user.nickname}</p>
          <p className="text-sm text-muted-foreground wrap-anywhere">{user.email}</p>
          <p className="text-xs text-muted-foreground">
            {formatDateTime(user.createdAt)} 가입
          </p>
        </div>

        {!!user.bio && (
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-medium text-foreground">자기소개</h3>
            <p className="whitespace-pre-wrap break-keep text-sm text-muted-foreground wrap-anywhere">{user.bio}</p>
          </div>
        )}

        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">이메일 인증</dt>
            <dd className="text-foreground">{formatDateTime(user.emailVerifiedAt)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">최근 활동</dt>
            <dd className="text-foreground">{formatDateTime(user.lastActiveAt)}</dd>
          </div>
          {/* 재지정해도 BE가 첫 지정 시각을 유지한다 — 베타 코호트 리텐션이 이 시각의 주로 묶인다. */}
          {!!user.betaJoinedAt && (
            <div>
              <dt className="text-muted-foreground">베타 지정</dt>
              <dd className="text-foreground">{formatDateTime(user.betaJoinedAt)}</dd>
            </div>
          )}
          {/* 허용 행이 있을 때만 — 재허용해도 BE가 첫 허용 시각을 유지하고, 회수하면 행이 지워져 사라진다. */}
          {!!user.novelizeGrantedAt && (
            <div>
              <dt className="text-muted-foreground">소설화 허용</dt>
              <dd className="text-foreground">{formatDateTime(user.novelizeGrantedAt)}</dd>
            </div>
          )}
        </dl>

        {/* 클로버 잔액을 여기 넣는 이유: 작품·채팅방·메시지와 같은 "이 유저의 현재 수치"이고,
         * 조치 패널의 지급·회수가 바로 이 숫자를 움직인다. 별도 섹션으로 떼면 조치와 그 대상이
         * 화면에서 멀어진다. */}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm @xl:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">작품수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(user.contentCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">채팅방수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(user.chatRoomCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">메시지수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(user.messageCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">클로버</dt>
            <dd className="tabular-nums text-foreground">{formatCount(user.cloverBalance)}</dd>
          </div>
        </dl>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
        <h2 className="text-lg font-semibold text-foreground">신고 이력</h2>
        {user.reports.length === 0 ? (
          <p className="text-sm text-muted-foreground">신고 이력이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <DenseTable surface="card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>대상 작품·댓글</TableHead>
                    <TableHead>사유</TableHead>
                    <TableHead>처리상태</TableHead>
                    <TableHead>신고일시</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {user.reports.map((report) => (
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
                      <DateTimeCell value={report.createdAt} />
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </DenseTable>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
        <h2 className="text-lg font-semibold text-foreground">조치 이력</h2>
        {user.actionLogs.length === 0 ? (
          <p className="text-sm text-muted-foreground">조치 이력이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <DenseTable surface="card">
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
                  {user.actionLogs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell>{ACTION_TYPE_LABELS[log.actionType]}</TableCell>
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
                        {!!log.targetCommentId && <p className="mt-1 break-all text-xs">댓글 {log.targetCommentId}</p>}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{reasonCategoryLabel(log.reasonCategory)}</TableCell>
                      {/* 운영자가 쓴 자유 글이라 길다 — 이 칸만 줄바꿈해 조치일시가 표 끝으로 밀려나지 않게 한다. */}
                      <TableCell className="min-w-48 whitespace-normal break-keep text-muted-foreground wrap-anywhere">
                        {log.reasonText || "-"}
                      </TableCell>
                      <DateTimeCell value={log.createdAt} />
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </DenseTable>
          </div>
        )}
      </section>

      <CloverLedgerSection userId={userId} />

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
        <h2 className="text-lg font-semibold text-foreground">채팅방</h2>
        {user.chatRooms.length === 0 ? (
          <p className="text-sm text-muted-foreground">채팅방이 없어요.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <DenseTable surface="card">
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
                  {user.chatRooms.map((chatRoom) => (
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
                      <TableCell className="min-w-24 whitespace-normal break-keep text-muted-foreground wrap-anywhere">
                        {chatRoom.name || "-"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(chatRoom.turnCount)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(chatRoom.messageCount)}</TableCell>
                      <DateTimeCell value={chatRoom.lastMessageAt} />
                      <DateTimeCell value={chatRoom.createdAt} />
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
            </DenseTable>
          </div>
        )}
      </section>

      {/* 같은 그리드를 두 벌 유지하지 않으려 링크만 둔다.
       * 유저 상세 응답(AdminUserDetailResponse)에 생성 이미지 건수 필드가 없어
       * "N건"은 못 붙이고 목적지만 알린다. */}
      <section className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-xl border border-border bg-card p-4 @xl:p-6">
        <h2 className="text-lg font-semibold text-foreground">생성 이미지</h2>
        <Link to="/users/$userId/image-generations" params={{ userId }} className={INLINE_LINK_CLASS}>
          생성 이미지 열람 →
        </Link>
      </section>

    </>
  );
}

type CloverLedgerSectionProps = {
  userId: string;
};

/** 원장은 상세 응답이 아니라 별도 라우트다 — 상세가 이미 목록 셋을
 * 싣고 있어 네 번째를 얹으면 한 요청이 무거워진다. 그래서 로딩·에러도 이 섹션이 따로 진다.
 *
 * 🔴 **첫 페이지 20건만** 쓴다(사용자 결정 — 전용 목록 페이지는 만들지 않는다). 그보다 오래된
 * 내역이 필요한 일은 아직 없고, 필요해지면 그때 `page`를 올리는 화면만 더하면 된다. */
function CloverLedgerSection({ userId }: CloverLedgerSectionProps) {
  const ledgerQuery = useCloverLedgerQuery(userId);

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold text-foreground">클로버 원장</h2>
        {ledgerQuery.isSuccess && ledgerQuery.data.totalCount > ledgerQuery.data.items.length && (
          <p className="text-xs text-muted-foreground">
            최근 {formatCount(ledgerQuery.data.items.length)}건 / 전체 {formatCount(ledgerQuery.data.totalCount)}건
          </p>
        )}
      </div>

      <CloverLedgerBody ledgerQuery={ledgerQuery} />
    </section>
  );
}

type CloverLedgerBodyProps = {
  ledgerQuery: ReturnType<typeof useCloverLedgerQuery>;
};

/** 섹션 제목은 로딩·에러에도 남아야 해서 원장에 의존하는 본문만 갈라내 early return으로 가른다. */
function CloverLedgerBody({ ledgerQuery }: CloverLedgerBodyProps) {
  if (ledgerQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-secondary" />;
  }

  if (ledgerQuery.isError) {
    return <p className="text-sm text-destructive-text">원장을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (ledgerQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">클로버가 오간 기록이 없어요.</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <DenseTable surface="card">
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
                <DateTimeCell value={item.createdAt} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DenseTable>
    </div>
  );
}

/** 원장은 증감이라 부호가 값의 일부다 — `formatCount`는 음수에 `-`만 붙이므로 지급 쪽에 `+`를
 * 손으로 붙인다. 0은 원장에 들어오지 않는다(BE가 `amount=0`을 거부한다). */
function formatSignedCount(amount: number) {
  return amount > 0 ? `+${formatCount(amount)}` : formatCount(amount);
}

/** 하단 바 한 줄 요약 — 조치가 바꾸는 상태(정지·면제·베타·소설화)만. 기본값(아님)은 붙이지 않는다. */
function userStatusSummary(user: AdminUserDetailResponse) {
  return [
    user.suspendedAt ? "정지" : "정상",
    user.rateLimitExempt && "면제",
    user.betaJoinedAt && "베타",
    user.novelizeGrantedAt && "소설화",
  ]
    .filter(Boolean)
    .join(" · ");
}

function reasonCategoryLabel(reasonCategory: string | null) {
  if (!reasonCategory) return "-";
  return REASON_CATEGORY_LABELS_ALL[reasonCategory] ?? reasonCategory;
}

type DateTimeCellProps = {
  value: string | null;
};

/** 표의 일시 칸. 자리가 넉넉하면 한 줄이고, 조치 열 옆 본문 열처럼 모자라면 날짜와 시각 사이에서만 두 줄로 꺾인다 —
 * 칸이 줄면서 "오전"이 갈라지거나 표가 가로로 스크롤되지 않게. */
function DateTimeCell({ value }: DateTimeCellProps) {
  if (!value) return <TableCell>-</TableCell>;
  const { date, time } = formatDateTimeParts(value);
  return (
    <TableCell className="whitespace-normal">
      <span className="whitespace-nowrap">{date}</span> <span className="whitespace-nowrap">{time}</span>
    </TableCell>
  );
}
