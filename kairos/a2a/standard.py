"""Standard A2A 1.x endpoints and SDK client for ADK ↔ CrewAI interoperability."""

import asyncio
import json
import uuid
from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message, Part, Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette

from kairos.observability.langfuse_tracing import observation
from kairos.schemas.analyst_reports import MarketAnalysisReport, SentimentAnalysisReport, NewsAnalysisReport, FundamentalsAnalysisReport, ResearchSynthesisVerdict
from kairos.utils.security import validate_ticker


class MarketExecutor(AgentExecutor):
    def __init__(self, analyst):
        self.analyst = analyst

    async def execute(self, context, event_queue):
        payload = json.loads(context.get_user_input())
        ticker = validate_ticker(payload["ticker"])
        report = await self.analyst.analyze_async(ticker, context.context_id)
        await event_queue.enqueue_event(Message(message_id=uuid.uuid4().hex, role=Role.ROLE_AGENT,
            parts=[Part(text=report.model_dump_json(), media_type="application/json")], context_id=context.context_id))

    async def cancel(self, context, event_queue):
        raise ValueError("Cancellation of an in-flight market tool call is not supported.")


class ResearchExecutor(AgentExecutor):
    def __init__(self, crew):
        self.crew = crew

    async def execute(self, context, event_queue):
        payload = json.loads(context.get_user_input())
        ticker = validate_ticker(payload["ticker"])
        schemas = {"market": MarketAnalysisReport, "sentiment": SentimentAnalysisReport,
                   "news": NewsAnalysisReport, "fundamentals": FundamentalsAnalysisReport}
        reports = {key: schema.model_validate(payload["analyst_reports"][key]).model_dump(mode="json") for key, schema in schemas.items()}
        if any(report["ticker"] != ticker for report in reports.values()):
            raise ValueError("A2A report bundle contains mismatched tickers.")
        verdict = await asyncio.to_thread(self.crew.conduct_debate, ticker, reports, context.context_id)
        await event_queue.enqueue_event(Message(message_id=uuid.uuid4().hex, role=Role.ROLE_AGENT,
            parts=[Part(text=verdict.model_dump_json(), media_type="application/json")], context_id=context.context_id))

    async def cancel(self, context, event_queue):
        raise ValueError("Cancellation of an in-flight research model call is not supported.")


def create_a2a_app(market_analyst, research_crew, base_url="http://kairos.local"):
    app = Starlette()
    for path, name, description, executor in [
        ("market", "KAIROS Market Analyst", "Google ADK market analysis with MCP tools and session state.", MarketExecutor(market_analyst)),
        ("research", "KAIROS Research Crew", "CrewAI Bull/Bear debate and research synthesis.", ResearchExecutor(research_crew)),
    ]:
        route = f"/a2a/{path}"
        card = AgentCard(name=name, description=description, version="1.0.0",
            supported_interfaces=[AgentInterface(url=base_url+route, protocol_binding="JSONRPC", protocol_version="1.0")],
            capabilities=AgentCapabilities(streaming=False), default_input_modes=["application/json"],
            default_output_modes=["application/json"],
            skills=[AgentSkill(id=path, name=name, description=description, tags=["equity-research"])])
        handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)
        app.routes.extend(create_agent_card_routes(card, card_url=route+"/.well-known/agent-card.json"))
        app.routes.extend(create_jsonrpc_routes(handler, route))
    return app


async def call_agent(app, name: str, payload: dict[str, Any], context_id: str | None = None):
    """Exercise the real HTTP/JSON-RPC protocol locally; the same routes are exposed by the API."""
    with observation("exchange-agent-report", "span", inputs={"recipient": name, "ticker": payload["ticker"]}, metadata={"protocol": "A2A", "version": "1.0"}) as span:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kairos.local", timeout=180) as http:
            factory = ClientFactory(ClientConfig(streaming=False, httpx_client=http))
            client = await factory.create_from_url("http://kairos.local/a2a/"+name)
            message = Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER,
                              parts=[Part(text=json.dumps(payload), media_type="application/json")])
            if context_id:
                message.context_id = context_id
            async for response in client.send_message(SendMessageRequest(message=message)):
                if response.HasField("message"):
                    parts = response.message.parts
                    for part in parts:
                        if part.text:
                            result = json.loads(part.text)
                            if span is not None:
                                span.update(output=result)
                            return result
                        if part.HasField("data"):
                            return MessageToDict(part.data)
        raise RuntimeError("A2A agent returned no structured report.")
