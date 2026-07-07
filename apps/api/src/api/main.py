from fastapi import FastAPI

app = FastAPI(title="AI 캐릭터 챗 API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
