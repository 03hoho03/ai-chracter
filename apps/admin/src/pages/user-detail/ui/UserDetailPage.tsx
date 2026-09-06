import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import { REASON_CATEGORY_LABELS, type ContentActionReasonCategory } from "@/entities/admin-content";
import { ACTION_TYPE_LABELS, SIGNUP_METHOD_LABELS, useUserDetailQuery } from "@/entities/admin-user";
import { REPORT_STATUS_LABELS } from "@/entities/report";
import { UserActionPanel } from "./UserActionPanel";

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

// 문장 속 링크는 `font-medium text-primary hover:underline`이 저장소 관용구다(MyPagePage 동형).
const INLINE_LINK_CLASS = "font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none";

function formatCount(value: number) {
  return value.toLocaleString("ko-KR");
}

function formatDateTime(value: string | null) {
  return value ? DATE_TIME_FORMATTER.format(new Date(value)) : "-";
}

/** `AdminUserActionLogItem.reasonCategory`는 enum이 아니라 plain `string | null`이다(작품 직접
 * 조치 로그와 같은 테이블을 써서 값이 섞인다) — `as` 대신 술어로 좁혀 아는 값만 라벨을 입힌다(TS-03). */
function isKnownReasonCategory(value: string): value is ContentActionReasonCategory {
  return value in REASON_CATEGORY_LABELS;
}

function reasonCategoryLabel(reasonCategory: string | null) {
  if (!reasonCategory) return "-";
  return isKnownReasonCategory(reasonCategory) ? REASON_CATEGORY_LABELS[reasonCategory] : reasonCategory;
}

type UserDetailPageProps = {
  userId: string;
};

export function UserDetailPage({ userId }: UserDetailPageProps) {
  const userDetailQuery = useUserDetailQuery(userId);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/users">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">유저 상세</h1>

      {userDetailQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {userDetailQuery.isError && (
        <p className="text-sm text-destructive-text">유저 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {userDetailQuery.data && (
        <>
          <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <span>{SIGNUP_METHOD_LABELS[userDetailQuery.data.signupMethod]}</span>
                <span aria-hidden>·</span>
                <span>{userDetailQuery.data.suspendedAt ? "정지" : "정상"}</span>
              </div>
              <p className="text-base font-semibold text-foreground">{userDetailQuery.data.nickname}</p>
              <p className="text-sm text-muted-foreground">{userDetailQuery.data.email}</p>
              <p className="text-xs text-muted-foreground">
                {DATE_TIME_FORMATTER.format(new Date(userDetailQuery.data.createdAt))} 가입
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

            <dl className="grid grid-cols-3 gap-x-6 gap-y-2 text-sm">
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
                          {REASON_CATEGORY_LABELS[report.reasonCategory]}
                        </TableCell>
                        <TableCell>{REPORT_STATUS_LABELS[report.status]}</TableCell>
                        <TableCell>{DATE_TIME_FORMATTER.format(new Date(report.createdAt))}</TableCell>
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
                        <TableCell>{DATE_TIME_FORMATTER.format(new Date(log.createdAt))}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </section>

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
                        <TableCell>{DATE_TIME_FORMATTER.format(new Date(chatRoom.createdAt))}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </section>

          <UserActionPanel
            userId={userDetailQuery.data.id}
            suspendedAt={userDetailQuery.data.suspendedAt}
            restrictableContentCount={userDetailQuery.data.restrictableContentCount}
          />
        </>
      )}
    </main>
  );
}
