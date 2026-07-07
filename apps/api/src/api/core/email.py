def send_email(to: str, subject: str, body: str) -> None:
    """No real email provider is chosen yet (techspec-backend-auth.md §5 leaves this
    an open item) — prints the outgoing email instead (a `logging.info` call would
    be silently dropped since nothing configures a root handler). Every call site
    goes through this one function, so swapping in a real provider (SES/SMTP) later
    only means changing this body, not any caller."""
    print(f"EMAIL to={to} subject={subject!r} body={body!r}")
