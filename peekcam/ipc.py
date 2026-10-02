"""Single-instance IPC over a Qt local socket.

Real global hotkeys are blocked on Wayland (even under XWayland), so instead the running
app listens on a named local socket and the *same* binary, invoked with an action flag,
forwards that action to the running instance. Users bind these invocations to keys via
GNOME Settings -> Keyboard -> Custom Shortcuts. See README.

Actions: toggle-clickthrough, snapshot, toggle-record, cycle-camera, show, show-hide, toggle-blur, quit.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "peekcam.ipc"
VALID_ACTIONS = {
    "toggle-clickthrough", "snapshot", "toggle-record",
    "cycle-camera", "show", "show-hide", "toggle-blur", "quit",
}


def send_action(action: str, timeout_ms: int = 800) -> bool:
    """Client side: try to hand an action to a running instance. True if delivered."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(action.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class IpcServer(QObject):
    action_received = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        if self._server.listen(SERVER_NAME):
            return True
        # A stale socket file from a crash blocks listen(); clear it and retry once.
        QLocalServer.removeServer(SERVER_NAME)
        return self._server.listen(SERVER_NAME)

    def _on_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda c=conn: self._on_ready(c))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready(self, conn: QLocalSocket) -> None:
        data = bytes(conn.readAll()).decode("utf-8", "ignore").strip()
        if data in VALID_ACTIONS:
            self.action_received.emit(data)
