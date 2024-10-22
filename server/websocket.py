# websocket.py

"""
This module handles WebSocket connections and spammer checks.
"""


import json
import logging
from twisted.internet import defer, reactor
from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory

LOGGER = logging.getLogger(__name__)

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

            if not (
                lols_bot_data.get("banned")
                or (
                    cas_chat_data.get("result")
                    and cas_chat_data["result"].get("offenses", 0) > 0
                )
            ):
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

                if lols_bot_data.get("banned") or cas_chat_data.get("ok"):
                    LOGGER.info("User detected as spammer during polling.")
                    return

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