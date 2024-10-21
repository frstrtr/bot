"""
p2p spammer database server with API and WebSocket.
Twisted-based solution.
Check if the user is in the LOLS bot database:
https://api.lols.bot/account?id=
https://api.cas.chat/check?user_id=
"""

import sys
import logging
import json
from twisted.internet import endpoints, defer, task, protocol
from twisted.internet import reactor
from twisted.web import server, resource
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory
from twisted.internet.ssl import CertificateOptions
from twisted.internet._sslverify import ClientTLSOptions
from twisted.web.iweb import IPolicyForHTTPS
from zope.interface import implementer

# Set up logging
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


@implementer(IPolicyForHTTPS)
class NoVerifyContextFactory:
    """A context factory that does not verify SSL certificates."""

    def __init__(self, hostname):
        self.hostname = hostname
        self.options = CertificateOptions(verify=False)

    def creatorForNetloc(self, hostname, port):
        """Function description here"""
        LOGGER.info("Creating context for %s: %s", hostname, port)
        return ClientTLSOptions(hostname, self.options.getContext())


class APIClient:
    """A helper class to fetch data from static endpoints using Twisted's Agent."""

    def __init__(self, hostname):
        self.agent = Agent(reactor, contextFactory=NoVerifyContextFactory(hostname))

    def fetch_data(self, url):
        """Fetch data from the given URL."""
        return self.agent.request(
            b"GET",
            url.encode("utf-8"),
            Headers({"User-Agent": ["Twisted P2P spam checker"]}),
            None,
        ).addCallback(readBody)


class SpammerCheckProtocol(WebSocketServerProtocol):
    """WebSocket protocol to handle spammer check requests."""

    def onOpen(self):
        LOGGER.info("WebSocket connection open.")

    def onMessage(self, payload, isBinary):
        if not isBinary:
            message = payload.decode("utf-8")
            LOGGER.info("Text message received: %s", message)
            data = json.loads(message)
            user_id = data.get("user_id")
            polling_duration = data.get(
                "polling_duration", 2 * 60 * 60
            )  # Default to 2 hours
            if user_id:
                self.check_spammer(user_id, polling_duration)

    def check_spammer(self, user_id, polling_duration):
        """Check if the user is a spammer using the LOLS and CAS APIs."""
        api_client_lols = APIClient("api.lols.bot")
        api_client_cas = APIClient("api.cas.chat")
        lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
        cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

        d1 = api_client_lols.fetch_data(lols_bot_url)
        d2 = api_client_cas.fetch_data(cas_chat_url)

        def handle_response(responses):
            lols_bot_response, cas_chat_response = responses
            LOGGER.info("LOLS bot response: %s", lols_bot_response.decode("utf-8"))
            LOGGER.info("CAS chat response: %s", cas_chat_response.decode("utf-8"))
            lols_bot_data = json.loads(lols_bot_response.decode("utf-8"))
            cas_chat_data = json.loads(cas_chat_response.decode("utf-8"))

            response = {
                "lols_bot": lols_bot_data,
                "cas_chat": cas_chat_data,
            }
            self.sendMessage(json.dumps(response).encode("utf-8"))
            LOGGER.info("Response sent: %s", response)

            # Check if the user is a spammer
            if not (
                lols_bot_data.get("banned")
                or (
                    cas_chat_data.get("result")
                    and cas_chat_data["result"].get("offenses", 0) > 0
                )
            ):
                # Start exponential backoff polling
                self.start_exponential_backoff_polling(user_id, polling_duration)

        defer.gatherResults([d1, d2]).addCallback(handle_response)

    def start_exponential_backoff_polling(self, user_id, polling_duration):
        api_client_lols = APIClient("api.lols.bot")
        api_client_cas = APIClient("api.cas.chat")
        lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
        cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

        interval = 60  # Start with a 1-minute interval
        end_time = reactor.seconds() + polling_duration

        def poll():
            if reactor.seconds() >= end_time:
                LOGGER.info("Polling duration ended.")
                return

            d1 = api_client_lols.fetch_data(lols_bot_url)
            d2 = api_client_cas.fetch_data(cas_chat_url)

            def handle_response(responses):
                lols_bot_response, cas_chat_response = responses
                LOGGER.info("LOLS bot response: %s", lols_bot_response.decode("utf-8"))
                LOGGER.info("CAS chat response: %s", cas_chat_response.decode("utf-8"))
                lols_bot_data = json.loads(lols_bot_response.decode("utf-8"))
                cas_chat_data = json.loads(cas_chat_response.decode("utf-8"))

                response = {
                    "lols_bot": lols_bot_data,
                    "cas_chat": cas_chat_data,
                }
                self.sendMessage(json.dumps(response).encode("utf-8"))
                LOGGER.info("Polling response sent: %s", response)

                # Check if the user is a spammer
                if lols_bot_data.get("banned") or cas_chat_data.get("ok"):
                    LOGGER.info("User detected as spammer during polling.")
                    return

                # Schedule the next poll with exponential backoff
                nonlocal interval
                interval = min(interval * 2, 3600)  # Max interval of 1 hour
                reactor.callLater(interval, poll)

            defer.gatherResults([d1, d2]).addCallback(handle_response)

        poll()

    def onClose(self, wasClean, code, reason):
        LOGGER.info("WebSocket connection closed: %s", reason)


class SpammerCheckFactory(WebSocketServerFactory):
    """WebSocket factory to create instances of SpammerCheckProtocol."""

    protocol = SpammerCheckProtocol


class SpammerCheckResource(resource.Resource):
    """HTTP resource to handle spammer check requests."""

    isLeaf = True

    def render_GET(self, request):
        """Handle GET requests by fetching data from the LOLS and CAS APIs."""
        user_id = request.args.get(b"user_id", [None])[0]
        if user_id:
            user_id = user_id.decode("utf-8")
            LOGGER.info("Received HTTP request for user_id: %s", user_id)
            api_client_lols = APIClient("api.lols.bot")
            api_client_cas = APIClient("api.cas.chat")
            lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
            cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

            d1 = api_client_lols.fetch_data(lols_bot_url)
            d2 = api_client_cas.fetch_data(cas_chat_url)

            def handle_response(responses):
                lols_bot_response, cas_chat_response = responses
                LOGGER.info("LOLS bot response: %s", lols_bot_response.decode("utf-8"))
                LOGGER.info("CAS chat response: %s", cas_chat_response.decode("utf-8"))
                response = {
                    "lols_bot": json.loads(lols_bot_response.decode("utf-8")),
                    "cas_chat": json.loads(cas_chat_response.decode("utf-8")),
                }
                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info("Response sent: %s", response)

            defer.gatherResults([d1, d2]).addCallback(handle_response)
            return server.NOT_DONE_YET
        else:
            request.setResponseCode(400)
            return b"Missing user_id parameter"


class P2PProtocol(protocol.Protocol):
    """P2P protocol to handle connections and exchange spammer information."""

    def connectionMade(self):
        self.factory.peers.append(self)
        peer = self.transport.getPeer()
        LOGGER.info("P2P connection made with %s:%d", peer.host, peer.port)
        LOGGER.info("P2P connection details: %s", peer)

    def dataReceived(self, data):
        message = data.decode("utf-8")
        LOGGER.info("P2P message received: %s", message)
        data = json.loads(message)
        user_id = data.get("user_id")
        if user_id:
            self.factory.broadcast_spammer_info(user_id)

    def connectionLost(self, reason):
        self.factory.peers.remove(self)
        LOGGER.info("P2P connection lost: %s", reason)


class P2PFactory(protocol.Factory):
    """Factory to manage P2P connections."""

    protocol = P2PProtocol

    def __init__(self):
        self.peers = []

    def broadcast_spammer_info(self, user_id):
        """Broadcast spammer information to all connected peers."""
        message = json.dumps({"user_id": user_id})
        for peer in self.peers:
            peer.transport.write(message.encode("utf-8"))
        LOGGER.info("Broadcasted spammer info: %s", message)


def main():
    """Main function to start the server."""
    if len(sys.argv) < 2:
        print("Usage: python3 p2spm.py <port> [peer1] [peer2] ...")
        sys.exit(1)

    port = int(sys.argv[1])
    peers = sys.argv[2:]

    LOGGER.info("Starting P2P server on port %d", port)

    # TODO implement WebHook to receive data from bot

    # Set up the WebSocket server
    ws_factory = SpammerCheckFactory()
    ws_endpoint = endpoints.TCP4ServerEndpoint(reactor, 9000)
    ws_endpoint.listen(ws_factory)
    LOGGER.info("WebSocket server listening on port 9000")

    # Set up the HTTP server
    root = resource.Resource()
    root.putChild(b"check", SpammerCheckResource())
    http_factory = server.Site(root)
    http_endpoint = endpoints.TCP4ServerEndpoint(reactor, 8080)
    http_endpoint.listen(http_factory)
    LOGGER.info("HTTP server listening on port 8080")

    # Set up the P2P server
    p2p_factory = P2PFactory()
    p2p_endpoint = endpoints.TCP4ServerEndpoint(reactor, 9001)
    p2p_endpoint.listen(p2p_factory)
    LOGGER.info("P2P server listening on port 9001")

    # Connect to peers
    for peer in peers:
        peer_host, peer_port = peer.split(":")
        peer_port = int(peer_port)
        peer_endpoint = endpoints.TCP4ClientEndpoint(reactor, peer_host, peer_port)
        peer_endpoint.connect(p2p_factory)
        LOGGER.info("Connecting to peer %s:%d", peer_host, peer_port)

    reactor.run()


if __name__ == "__main__":
    main()
