# api.py

"""
This module handles API requests and responses.
"""

import json
import logging
from twisted.web import server, resource
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet import defer, reactor
from twisted.web.iweb import IPolicyForHTTPS
from twisted.internet.ssl import CertificateOptions
from twisted.internet._sslverify import ClientTLSOptions
from zope.interface import implementer
from database import retrieve_spammer_data, store_spammer_data


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


class SpammerCheckResource(resource.Resource):
    """HTTP resource to handle spammer check requests."""

    isLeaf = True

    def render_GET(self, request):
        """Handle GET requests by fetching data from the database, P2P network, and static APIs."""
        user_id = request.args.get(b"user_id", [None])[0]
        if user_id:
            user_id = user_id.decode("utf-8")
            LOGGER.info("Received HTTP request for user_id: %s", user_id)

            # Check database first
            spammer_data = retrieve_spammer_data(user_id)
            if spammer_data:
                response = {
                    "ok": True,
                    "user_id": user_id,
                    "is_spammer": self.is_spammer(spammer_data),
                    "lols_bot": json.loads(spammer_data["lols_bot_data"]),
                    "cas_chat": json.loads(spammer_data["cas_chat_data"]),
                    "p2p": json.loads(spammer_data["p2p_data"]),
                }
                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info("Response sent from database: %s", response)
                return server.NOT_DONE_YET

            # Check P2P network secondly
            p2p_data = self.check_p2p_data(user_id)
            if p2p_data:
                response = {
                    "ok": True,
                    "user_id": user_id,
                    "is_spammer": self.is_spammer(p2p_data),
                    "lols_bot": json.loads(p2p_data["lols_bot_data"]),
                    "cas_chat": json.loads(p2p_data["cas_chat_data"]),
                    "p2p": json.loads(p2p_data["p2p_data"]),
                }
                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info("Response sent from P2P network: %s", response)
                return server.NOT_DONE_YET

            # Check static APIs finally
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

                is_spammer = (
                    lols_bot_data.get("banned", False)
                    or cas_chat_data.get("result", {}).get("offenses", 0) > 0
                )

                p2p_data = self.check_p2p_data(user_id)

                response = {
                    "ok": True,
                    "user_id": user_id,
                    "is_spammer": is_spammer,
                    "lols_bot": lols_bot_data,
                    "cas_chat": cas_chat_data,
                    "p2p": p2p_data,
                }

                # Store the data in the database
                store_spammer_data(
                    user_id,
                    json.dumps(lols_bot_data),
                    json.dumps(cas_chat_data),
                    json.dumps(p2p_data),
                )

                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info("Response sent from static APIs: %s", response)

            def handle_error(failure):
                LOGGER.error("Error querying APIs: %s", failure)
                response = {
                    "ok": False,
                    "user_id": user_id,
                    "error": str(failure),
                }
                request.setHeader(b"content-type", b"application/json")
                request.write(json.dumps(response).encode("utf-8"))
                request.finish()
                LOGGER.info("Error response sent: %s", response)

            d = defer.gatherResults([d1, d2])
            d.addCallback(handle_response)
            d.addErrback(handle_error)
            return server.NOT_DONE_YET
        else:
            request.setResponseCode(400)
            return b"Missing user_id parameter"

    def check_p2p_data(self, user_id):
        """Placeholder function to check for P2P data."""
        reply = {
            "ok": True,
            "user_id": user_id,
        }
        return reply

    def is_spammer(self, data):
        """Determine if the user is a spammer based on the data."""
        lols_bot_data = json.loads(data["lols_bot_data"])
        cas_chat_data = json.loads(data["cas_chat_data"])
        return (
            lols_bot_data.get("banned", False)
            or cas_chat_data.get("result", {}).get("offenses", 0) > 0
        )
