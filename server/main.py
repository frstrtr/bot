import sys
import uuid
from twisted.internet import reactor, endpoints
from twisted.web import server, resource
from p2p import P2PFactory, find_available_port
from websocket import SpammerCheckFactory
from api import SpammerCheckResource
from config import (
    LOGGER,
    DEFAULT_P2P_PORT,
    WEBSOCKET_PORT,
    HTTP_PORT,
    BOOTSTRAP_ADDRESSES,
)
from database import initialize_database


def main():
    """Main function to start the server."""

    # Initialize the database
    initialize_database()

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
