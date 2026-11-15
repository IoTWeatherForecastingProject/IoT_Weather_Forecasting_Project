import asyncio
import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app, ws_manager, ConnectionManager


def test_websocket_connect_and_disconnect():
    """Kiểm tra client kết nối WebSocket thành công và ngắt kết nối an toàn."""
    client = TestClient(app)
    initial_count = len(ws_manager.active_connections)

    with client.websocket_connect("/ws/weather/live") as websocket:
        assert len(ws_manager.active_connections) == initial_count + 1
        # Gửi message ping thử nghiệm
        websocket.send_text("ping")

    # Sau khi thoát context manager, client ngắt kết nối
    assert len(ws_manager.active_connections) == initial_count


@pytest.mark.asyncio
async def test_websocket_broadcast_multiple_clients_concurrent():
    """Kiểm tra broadcast đồng thời cho 5 clients (tương đương 5 tab Dashboard SCADA) mà không nghẽn."""
    test_manager = ConnectionManager()

    class MockWebSocket:
        def __init__(self, client_id: int):
            self.client_id = client_id
            self.received_messages = []
            self.is_closed = False

        async def accept(self):
            pass

        async def send_text(self, text: str):
            if self.is_closed:
                raise RuntimeError("Connection closed")
            self.received_messages.append(text)

        async def close(self):
            self.is_closed = True

    # Tạo 5 client mock kết nối đồng thời
    clients = [MockWebSocket(i) for i in range(5)]
    for ws in clients:
        await test_manager.connect(ws)

    assert len(test_manager.active_connections) == 5

    # Broadcast payload chứa cả datetime object
    payload = {
        "device_id": "station01",
        "timestamp": datetime.now(timezone.utc),
        "temperature": 31.25,
        "humidity": 78.40,
        "pressure": 1005.80,
        "rain_detected": 0
    }

    await test_manager.broadcast(payload)

    # Đảm bảo cả 5 client đều nhận đúng dữ liệu broadcast
    for ws in clients:
        assert len(ws.received_messages) == 1
        received = json.loads(ws.received_messages[0])
        assert received["device_id"] == "station01"
        assert received["temperature"] == 31.25
        assert "timestamp" in received


@pytest.mark.asyncio
async def test_websocket_dead_connection_cleanup():
    """Kiểm tra cơ chế tự động dọn dẹp kết nối hỏng (dead connection) khi client ngắt đột ngột."""
    test_manager = ConnectionManager()

    class NormalWebSocket:
        def __init__(self):
            self.received = []

        async def accept(self):
            pass

        async def send_text(self, text: str):
            self.received.append(text)

        async def close(self):
            pass

    class BrokenWebSocket:
        async def accept(self):
            pass

        async def send_text(self, text: str):
            raise ConnectionResetError("Mất kết nối mạng đột ngột")

        async def close(self):
            pass

    normal_client = NormalWebSocket()
    broken_client = BrokenWebSocket()

    await test_manager.connect(normal_client)
    await test_manager.connect(broken_client)
    assert len(test_manager.active_connections) == 2

    # Broadcast dữ liệu
    await test_manager.broadcast({"message": "live_update"})

    # Client hỏng phải bị loại bỏ, client bình thường vẫn nhận được
    assert len(test_manager.active_connections) == 1
    assert normal_client in test_manager.active_connections
    assert broken_client not in test_manager.active_connections
    assert len(normal_client.received) == 1
