import asyncio
import json
import logging
import threading
import time
from django.conf import settings

logger = logging.getLogger(__name__)

# Connected client sets
_connected_clients = set()
_user_clients = {}  # user_id or outer_id -> set of websockets
_lock = threading.Lock()
_event_loop = None
_server_started = False


async def register_client(websocket):
    with _lock:
        _connected_clients.add(websocket)
    logger.info(f"[WebSocket] Client connected. Total active clients: {len(_connected_clients)}")


async def unregister_client(websocket):
    with _lock:
        _connected_clients.discard(websocket)
        for uid in list(_user_clients.keys()):
            _user_clients[uid].discard(websocket)
            if not _user_clients[uid]:
                _user_clients.pop(uid, None)
    logger.info(f"[WebSocket] Client disconnected. Total active clients: {len(_connected_clients)}")


async def handle_client(websocket):
    await register_client(websocket)
    try:
        # Send initial welcome message
        welcome = {
            'type': 'connection.established',
            'message': 'Connected to Employee Service WebSocket',
            'timestamp': time.time(),
        }
        await websocket.send(json.dumps(welcome))

        async for message in websocket:
            try:
                msg_data = json.loads(message)
                msg_type = msg_data.get('type')

                if msg_type == 'ping':
                    await websocket.send(json.dumps({'type': 'pong', 'timestamp': time.time()}))
                elif msg_type == 'subscribe':
                    user_id = str(msg_data.get('user_id') or msg_data.get('outer_id') or '')
                    if user_id:
                        with _lock:
                            if user_id not in _user_clients:
                                _user_clients[user_id] = set()
                            _user_clients[user_id].add(websocket)
                        logger.info(f"[WebSocket] Client subscribed to user: {user_id}")
                        await websocket.send(json.dumps({'type': 'subscribed', 'user_id': user_id}))
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.warning(f"[WebSocket] Error processing client message: {e}")
    except Exception as exc:
        logger.info(f"[WebSocket] Connection closed: {exc}")
    finally:
        await unregister_client(websocket)


async def _async_broadcast(event_type: str, data: dict):
    """
    Sends message to all connected clients and/or user-specific clients.
    """
    message = json.dumps({
        'event': event_type,
        'type': event_type,
        'data': data,
        'employee': data,
        'timestamp': time.time(),
    })

    targets = set()
    with _lock:
        targets = set(_connected_clients)

    if not targets:
        logger.debug(f"[WebSocket] No active clients to broadcast {event_type}")
        return

    logger.info(f"[WebSocket] Broadcasting {event_type} to {len(targets)} clients for employee: {data.get('username') or data.get('id')}")
    dead_clients = []
    for client in targets:
        try:
            await client.send(message)
        except Exception as e:
            logger.warning(f"[WebSocket] Failed to send to a client: {e}")
            dead_clients.append(client)

    if dead_clients:
        with _lock:
            for dead in dead_clients:
                _connected_clients.discard(dead)


def broadcast_employee_event(event_type: str, data: dict):
    """
    Thread-safe synchronous function to dispatch event to WebSocket clients.
    Can be called from Django views, signals, or Celery tasks.
    """
    global _event_loop
    if _event_loop and _event_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(_async_broadcast(event_type, data), _event_loop)
            logger.info(f"[WebSocket] Dispatched broadcast job for {event_type}")
            return True
        except Exception as exc:
            logger.error(f"[WebSocket] Failed to schedule broadcast: {exc}")
            return False
    else:
        logger.warning("[WebSocket] Event loop not running, could not broadcast directly")
        return False


def _run_websocket_server():
    global _event_loop
    import websockets

    _event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_event_loop)

    host = getattr(settings, 'WS_HOST', '0.0.0.0')
    port = getattr(settings, 'WS_PORT', 8003)

    async def main():
        async with websockets.serve(handle_client, host, port):
            logger.info(f"[WebSocket] Server listening on ws://{host}:{port}")
            await asyncio.Future()  # run forever

    try:
        _event_loop.run_until_complete(main())
    except Exception as exc:
        logger.error(f"[WebSocket] Server error: {exc}", exc_info=True)


def _run_rabbitmq_ws_bridge():
    """
    Kombu background listener that subscribes to employee.* events from RabbitMQ
    and forwards them to WebSocket clients. This ensures events published by
    external Celery workers or other processes trigger WebSocket push.
    """
    from kombu import Connection, Exchange, Queue
    import time

    exchange = Exchange(settings.RABBITMQ_EXCHANGE, type='topic', durable=True)
    queue = Queue('employee_ws_bridge_queue', exchange=exchange, routing_key='employee.*', durable=True)

    while True:
        try:
            with Connection(settings.RABBITMQ_URL, connect_timeout=5.0) as conn:
                logger.info("[WebSocket Bridge] Connected to RabbitMQ for employee.* events")
                with conn.Consumer(queues=[queue], callbacks=[_on_bridge_message], no_ack=True):
                    while True:
                        try:
                            conn.drain_events(timeout=2.0)
                        except TimeoutError:
                            pass
                        except Exception as de_err:
                            if "timed out" not in str(de_err).lower():
                                raise
        except Exception as exc:
            logger.warning(f"[WebSocket Bridge] Disconnected ({exc}). Retrying in 5s...")
            time.sleep(5)


def _on_bridge_message(body, message):
    try:
        if isinstance(body, str):
            payload = json.loads(body)
        elif isinstance(body, dict):
            payload = body
        else:
            payload = json.loads(message.body.decode('utf-8'))

        event_type = payload.get('event') or 'employee.created'
        data = payload.get('data') or {}
        broadcast_employee_event(event_type, data)
    except Exception as err:
        logger.error(f"[WebSocket Bridge] Error handling message: {err}")


def start_websocket_server_thread():
    """
    Starts the WebSocket server and the RabbitMQ bridge daemon threads.
    """
    global _server_started
    if _server_started:
        return
    _server_started = True

    # Start WebSocket Server Thread
    ws_thread = threading.Thread(target=_run_websocket_server, name="EmployeeWebSocketServer", daemon=True)
    ws_thread.start()

    # Start RabbitMQ-to-WebSocket Bridge Thread
    bridge_thread = threading.Thread(target=_run_rabbitmq_ws_bridge, name="EmployeeWSBridge", daemon=True)
    bridge_thread.start()

    logger.info("[WebSocket] Started WebSocket server and RabbitMQ bridge background threads")
