import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.endpoints import router as weather_router
from app.schemas.weather import HealthCheckResponse
from app.ingestion.mqtt_worker import MQTTIngestionWorker
from app.db.session import check_db_connection

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("weather_backend")


# --- Quản lý kết nối WebSocket tập trung (Connection Manager) ---
class ConnectionManager:
    """Quản lý danh sách các kết nối WebSocket đang hoạt động và broadcast dữ liệu realtime."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Chấp nhận kết nối WebSocket mới và thêm vào danh sách quản lý."""
        await websocket.accept()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)
        logger.info("[WEBSOCKET] Client ket noi thanh cong. Tong so client dang online: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        """Hủy theo dõi kết nối khi client ngắt hoặc bị mất kết nối."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("[WEBSOCKET] Client ngat ket noi. So client con lai: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        """Phát sóng dữ liệu JSON xuống tất cả client đang kết nối và tự động dọn dẹp các kết nối hỏng."""
        if not self.active_connections:
            return

        text = json.dumps(message, default=str)
        dead_connections: List[WebSocket] = []

        # Tạo bản sao danh sách để đảm bảo an toàn khi duyệt
        for connection in list(self.active_connections):
            try:
                await connection.send_text(text)
            except Exception as e:
                logger.warning("[WEBSOCKET] Phat hien ket noi hong khi broadcast: %s", e)
                dead_connections.append(connection)

        # Dọn dẹp các kết nối lỗi
        for dead in dead_connections:
            self.disconnect(dead)
            try:
                await dead.close()
            except Exception:
                pass


ws_manager = ConnectionManager()
mqtt_worker = None
loop_ref = None


def on_mqtt_data_received(data: dict):
    """Callback từ MQTT worker luồng nền chuyển dữ liệu vào async event loop để broadcast WebSocket."""
    if loop_ref and not loop_ref.is_closed():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(data), loop_ref)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời ứng dụng FastAPI: Khởi động và dừng an toàn MQTT Ingestion Worker."""
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


openapi_tags = [
    {
        "name": "Weather",
        "description": "Các API truy vấn dữ liệu đo lường thời gian thực, lịch sử chuỗi thời gian, dự báo AI và cấu hình ngưỡng cảnh báo."
    },
    {
        "name": "Health",
        "description": "Kiểm tra sức khỏe hệ thống (trạng thái CSDL PostgreSQL, MQTT Broker và các kênh WebSocket)."
    }
]

app = FastAPI(
    title="IoT Local Weather Monitoring & Forecasting API",
    description=(
        "Hệ thống Backend FastAPI thu thập và xử lý dữ liệu từ trạm quan trắc thời tiết IoT cục bộ.\n\n"
        "- **CSDL Chuỗi Thời Gian:** Lưu trữ PostgreSQL tối ưu Composite Index cho truy vấn sliding window.\n"
        "- **Kênh Realtime WebSocket:** Đẩy dữ liệu live stream xuống giao diện SCADA Dashboard.\n"
        "- **AI Dự báo & Cảnh báo khép kín:** Tích hợp mô hình chuỗi thời gian và vòng lặp actuation 2 chiều."
    ),
    version="1.0.0",
    openapi_tags=openapi_tags,
    lifespan=lifespan
)

# Cấu hình CORS cho phép Dashboard SCADA truy cập an toàn
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn Router API thời tiết
app.include_router(weather_router)


@app.get(
    "/api/health",
    response_model=HealthCheckResponse,
    tags=["Health"],
    summary="Kiểm tra sức khỏe hệ thống Backend",
    description="Kiểm tra trạng thái kết nối CSDL PostgreSQL, MQTT Broker và số lượng client WebSocket đang kết nối."
)
def health_check():
    """Kiểm tra tình trạng hoạt động của CSDL, MQTT Broker và các kênh WebSocket."""
    db_connected = check_db_connection()
    mqtt_connected = bool(mqtt_worker and mqtt_worker.client and mqtt_worker.client.is_connected())
    return HealthCheckResponse(
        status="online" if db_connected else "degraded",
        service="IoT Weather Backend",
        database_connected=db_connected,
        mqtt_connected=mqtt_connected,
        active_ws_clients=len(ws_manager.active_connections)
    )


@app.websocket("/ws/weather/live")
async def websocket_live_weather(websocket: WebSocket):
    """Kênh WebSocket đẩy dữ liệu thời tiết realtime xuống Dashboard SCADA."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Nhận ping/heartbeat từ client (nếu có) để duy trì kết nối
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("[WEBSOCKET] Ngoai le tren kenh WebSocket client: %s", e)
        ws_manager.disconnect(websocket)
