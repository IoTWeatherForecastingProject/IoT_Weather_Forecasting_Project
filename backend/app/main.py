import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.endpoints import router as weather_router
from app.ingestion.mqtt_worker import MQTTIngestionWorker

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("weather_backend")


# --- Quản lý kết nối WebSocket tập trung ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("[WEBSOCKET] Client connected. Total active: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("[WEBSOCKET] Client disconnected. Remaining: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        text = json.dumps(message)
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except Exception as e:
                logger.warning("[WEBSOCKET] Failed to send to a client, marking dead: %s", e)
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)


ws_manager = ConnectionManager()
mqtt_worker = None
loop_ref = None


def on_mqtt_data_received(data: dict):
    """Callback từ MQTT worker luồng nền chuyển dữ liệu vào async event loop để broadcast WebSocket."""
    if loop_ref and not loop_ref.is_closed():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(data), loop_ref)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_worker, loop_ref
    loop_ref = asyncio.get_running_loop()
    logger.info("[STARTUP] Khoi dong ung dung FastAPI Weather Backend...")

    # Khởi động MQTT Ingestion Worker
    mqtt_worker = MQTTIngestionWorker(broadcast_callback=on_mqtt_data_received)
    mqtt_worker.start()

    yield

    logger.info("[SHUTDOWN] Dang dung MQTT Ingestion Worker...")
    if mqtt_worker:
        mqtt_worker.stop()
    logger.info("[SHUTDOWN] Tat ung dung thanh cong.")


app = FastAPI(
    title="IoT Local Weather Monitoring & Forecasting API",
    description="Hệ thống backend tiếp nhận dữ liệu thời tiết MQTT, lưu trữ CSDL chuỗi thời gian, tích hợp AI dự báo và điều khiển cảnh báo 2 chiều.",
    version="1.0.0",
    lifespan=lifespan
)

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn Router API
app.include_router(weather_router)


@app.get("/api/health", tags=["Health"])
def health_check():
    return {
        "status": "online",
        "service": "IoT Weather Backend",
        "mqtt_connected": mqtt_worker.client.is_connected() if mqtt_worker else False,
        "active_ws_clients": len(ws_manager.active_connections)
    }


@app.websocket("/ws/weather/live")
async def websocket_live_weather(websocket: WebSocket):
    """Kênh WebSocket đẩy dữ liệu thời tiết realtime xuống Dashboard SCADA."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Nhận ping từ client (nếu có) để duy trì kết nối
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("[WEBSOCKET] Exception: %s", e)
        ws_manager.disconnect(websocket)

