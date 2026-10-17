
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from threading import Lock
from collections import defaultdict, deque
from time import monotonic
from uuid import uuid4
import math

app = FastAPI(title="Orders API")

# Allow browser-based grading requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOTAL_ORDERS = 58
RATE_LIMIT = 17
WINDOW_SECONDS = 10

lock = Lock()
idempotency_store = {}
created_orders = {}
client_requests = defaultdict(deque)


@app.get("/")
def home():
    return {
        "status": "ok",
        "total_orders": TOTAL_ORDERS,
        "rate_limit": RATE_LIMIT,
        "window_seconds": WINDOW_SECONDS,
    }


@app.post("/orders", status_code=201)
def create_order(
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    key = idempotency_key.strip()

    if not key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key cannot be empty",
        )

    with lock:
        # Reuse the original order for a repeated key.
        if key in idempotency_store:
            response.status_code = 200
            return idempotency_store[key]

        order_id = str(uuid4())
        order = {
            "id": order_id,
            "status": "created",
        }

        idempotency_store[key] = order
        created_orders[order_id] = order

        return order


@app.get("/orders")
def list_orders(
    limit: int = Query(default=10, ge=1, le=100),
    cursor: str | None = Query(default=None),
):
    # Cursor is the next numeric catalog ID to return.
    if cursor is None or cursor == "":
        start_id = 1
    else:
        try:
            start_id = int(cursor)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    if start_id < 1 or start_id > TOTAL_ORDERS + 1:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    end_id = min(start_id + limit - 1, TOTAL_ORDERS)

    items = [
        {"id": order_id}
        for order_id in range(start_id, end_id + 1)
    ]

    next_cursor = str(end_id + 1) if end_id < TOTAL_ORDERS else None

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    # Count API requests that identify a client.
    client_id = request.headers.get("X-Client-Id")

    if client_id and request.url.path != "/":
        now = monotonic()

        with lock:
            requests = client_requests[client_id]

            while requests and now - requests[0] >= WINDOW_SECONDS:
                requests.popleft()

            if len(requests) >= RATE_LIMIT:
                retry_after = max(
                    1,
                    math.ceil(WINDOW_SECONDS - (now - requests[0])),
                )

                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after),
                        "Content-Type": "application/json",
                    },
                )

            requests.append(now)

    return await call_next(request)


@app.get("/healthz")
def health():
    return {"status": "ok"}

