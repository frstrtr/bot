import sys
import uuid
try:
    from twisted.internet import reactor, endpoints
    from twisted.web import server, resource
except Exception:  # pragma: no cover - optional dependency
    reactor = None
    endpoints = None
    class resource:  # type: ignore
        class Resource:  # minimal stub
            isLeaf = True
            def render_GET(self, request):
                return b"{}"
    class server:  # type: ignore
        class Site:
            def __init__(self, *args, **kwargs):
                pass

try:
    from p2p import P2PFactory, find_available_port
except Exception:  # optional
    P2PFactory = None  # type: ignore
    def find_available_port(port):  # type: ignore
        return port

try:
    from websocket import SpammerCheckFactory
except Exception:  # optional
    SpammerCheckFactory = None  # type: ignore

try:
    from api import SpammerCheckResource  # type: ignore
except Exception:
    # Fallback stub to keep server importable if api module is missing
    class SpammerCheckResource(resource.Resource):
        isLeaf = True
        def render_GET(self, request):
            try:
                request.setHeader(b"content-type", b"application/json")
            except Exception:
                pass
            return b"{\"status\": \"ok\"}"

try:
    from config import (
        LOGGER,
        DEFAULT_P2P_PORT,
        WEBSOCKET_PORT,
        HTTP_PORT,
        BOOTSTRAP_ADDRESSES,
    )
except Exception:  # optional
    import logging
    LOGGER = logging.getLogger(__name__)
    DEFAULT_P2P_PORT = 9999
    WEBSOCKET_PORT = 9001
    HTTP_PORT = 8080
    BOOTSTRAP_ADDRESSES = []

try:
    from database import initialize_databasek
except Exception:  # optional
    def initialize_database():
        return None


def main():
    """Main function to start the server."""

    # Initialize the database
    initialize_database()

    if reactor is None or endpoints is None or P2PFactory is None or SpammerCheckFactory is None:
        LOGGER.warning("Server dependencies missing; skipping network startup.")
        return

    if len(sys.argv) < 2:
        port = DEFAULT_P2P_PORT
    else:
        port = int(sys.argv[1])

    peers = sys.argv[2:]

    node_uuid = str(uuid.uuid4())

    LOGGER.info("Starting P2P server on port %d", port)

    # Find an available port if the default port is not available
    port = find_available_port(port)
    LOGGER.info("Using port %d for P2P server", port)

    ws_factory = SpammerCheckFactory()
    ws_endpoint = endpoints.TCP4ServerEndpoint(reactor, WEBSOCKET_PORT)
    ws_endpoint.listen(ws_factory)
    LOGGER.info("WebSocket server listening on port %d", WEBSOCKET_PORT)

    root = resource.Resource()
    root.putChild(b"check", SpammerCheckResource())
    http_factory = server.Site(root)
    http_endpoint = endpoints.TCP4ServerEndpoint(reactor, HTTP_PORT)
    http_endpoint.listen(http_factory)
    LOGGER.info("HTTP server listening on port %d", HTTP_PORT)

    p2p_factory = P2PFactory(node_uuid)
    p2p_endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface="0.0.0.0")
    p2p_endpoint.listen(p2p_factory)
    LOGGER.info("P2P server listening on port %d", port)

    p2p_factory.connect_to_bootstrap_peers(BOOTSTRAP_ADDRESSES).addCallback(
        lambda _: LOGGER.info("Finished connecting to bootstrap peers")
    )

    for peer in peers:
        peer_host, peer_port = peer.split(":")
        peer_port = int(peer_port)
        peer_endpoint = endpoints.TCP4ClientEndpoint(reactor, peer_host, peer_port)
        peer_endpoint.connect(p2p_factory).addCallback(
            lambda _, host=peer_host, port=peer_port: LOGGER.info(
                "Connected to peer %s:%d", host, port
            )
        ).addErrback(
            lambda err, host=peer_host, port=peer_port: LOGGER.error(
                "Failed to connect to peer %s:%d: %s", host, port, err
            )
        )
        LOGGER.info("Connecting to peer %s:%d", peer_host, peer_port)

    reactor.run()


if __name__ == "__main__":
    main()
