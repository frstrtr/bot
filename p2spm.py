# p2p spammer database server with api and websocket
# twisted based solution
# Check if the user is in the lols bot database
# https://api.lols.bot/account?id=
# https://api.cas.chat/check?user_id=

from twisted.internet import reactor, protocol
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet.defer import inlineCallbacks, returnValue
from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory
import json


class APIClient:
    def __init__(self):
        self.agent = Agent(reactor)

    @inlineCallbacks
    def fetch_data(self, url):
        response = yield self.agent.request(
            b"GET",
            url.encode("utf-8"),
            Headers({"User-Agent": ["Twisted Web Client Example"]}),
            None,
        )
        body = yield readBody(response)
        returnValue(body.decode("utf-8"))


class SpammerCheckProtocol(WebSocketServerProtocol):
    def onConnect(self, request):
        print(f"Client connecting: {request.peer}")

    def onOpen(self):
        print("WebSocket connection open.")

    @inlineCallbacks
    def onMessage(self, payload, isBinary):
        if not isBinary:
            message = payload.decode("utf-8")
            data = json.loads(message)
            user_id = data.get("user_id")
            if user_id:
                api_client = APIClient()
                lols_bot_url = f"https://api.lols.bot/account?id={user_id}"
                cas_chat_url = f"https://api.cas.chat/check?user_id={user_id}"

                lols_bot_response = yield api_client.fetch_data(lols_bot_url)
                cas_chat_response = yield api_client.fetch_data(cas_chat_url)

                response = {
                    "lols_bot": json.loads(lols_bot_response),
                    "cas_chat": json.loads(cas_chat_response),
                }

                self.sendMessage(json.dumps(response).encode("utf-8"))

    def onClose(self, wasClean, code, reason):
        print(f"WebSocket connection closed: {reason}")


class SpammerCheckFactory(WebSocketServerFactory):
    protocol = SpammerCheckProtocol


def main():
    factory = SpammerCheckFactory()
    reactor.listenTCP(9000, factory)
    reactor.run()


if __name__ == "__main__":
    main()
