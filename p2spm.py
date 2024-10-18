"""
p2p spammer database server with API and WebSocket.
Twisted-based solution.
Check if the user is in the LOLS bot database:
https://api.lols.bot/account?id=
https://api.cas.chat/check?user_id=
"""

import json
from twisted.internet import reactor, endpoints, defer
from twisted.web import server, resource
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory
from twisted.internet.ssl import CertificateOptions
from twisted.internet._sslverify import ClientTLSOptions
from twisted.web.iweb import IPolicyForHTTPS
from zope.interface import implementer
import logging

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
            Headers({"User-Agent": ["Twisted Web Client Example"]}),
            None,
        ).addCallback(readBody)


class SpammerCheckProtocol(WebSocketServerProtocol):
    """WebSocket protocol to handle spammer check requests."""

    def onOpen(self):
        LOGGER.info("WebSocket connection open.")

    def onMessage(self, payload, isBinary):
        if not isBinary:
            message = payload.decode("utf-8")
            LOGGER.info(f"Text message received: {message}")
            data = json.loads(message)
            user_id = data.get("user_id")
            if user_id:
                api_client = APIClient("api.lols.bot")
                lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
                cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

                d1 = api_client.fetch_data(lols_bot_url)
                d2 = api_client.fetch_data(cas_chat_url)

                def handle_response(responses):
                    lols_bot_response, cas_chat_response = responses
                    LOGGER.info(
                        f"LOLS bot response: {lols_bot_response.decode('utf-8')}"
                    )
                    LOGGER.info(
                        f"CAS chat response: {cas_chat_response.decode('utf-8')}"
                    )
                    response = {
                        "lols_bot": json.loads(lols_bot_response.decode("utf-8")),
                        "cas_chat": json.loads(cas_chat_response.decode("utf-8")),
                    }
                    self.sendMessage(json.dumps(response).encode("utf-8"))
                    LOGGER.info(f"Response sent: {response}")

                defer.gatherResults([d1, d2]).addCallback(handle_response)

    def onClose(self, wasClean, code, reason):
        LOGGER.info(f"WebSocket connection closed: {reason}")


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
            LOGGER.info(f"Received HTTP request for user_id: {user_id}")
            api_client_lols = APIClient("api.lols.bot")
            api_client_cas = APIClient("api.cas.chat")
            lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
            cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

            d1 = api_client_lols.fetch_data(lols_bot_url)
            d2 = api_client_cas.fetch_data(cas_chat_url)

            def handle_response(responses):
                lols_bot_response, cas_chat_response = responses
                LOGGER.info(f"LOLS bot response: {lols_bot_response.decode('utf-8')}")
                LOGGER.info(f"CAS chat response: {cas_chat_response.decode('utf-8')}")
                response = {
                    "lols_bot": json.loads(lols_bot_response.decode("utf-8")),
                    "cas_chat": json.loads(cas_chat_response.decode("utf-8")),
                }
                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info(f"Response sent: {response}")

            defer.gatherResults([d1, d2]).addCallback(handle_response)
            return server.NOT_DONE_YET
        else:
            request.setResponseCode(400)
            return b"Missing user_id parameter"


def main():
    """Main function to start the server."""
    LOGGER.info("Starting server...")
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

    reactor.run()


if __name__ == "__main__":
    main()
