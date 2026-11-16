# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated by the user: React/TypeScript frontend, Python API, streamed execution events. Only Google ADK and CrewAI may be used as agentic frameworks. A2A is the interoperability protocol; MCP provides external tools. Langfuse provides observability.

## Users

Individual Indian-equity researchers are the primary audience. Project evaluators need an inspectable evidence view showing agent execution, tool calls, validated state, provenance, timings and costs.

## Product Purpose

KAIROS turns market, financial, news and sentiment evidence into a debated and explained investment proposal. Users select a stock and risk preference, watch actual agent activity, inspect Bull/Bear arguments and understand the final proposal.

## Positioning

Indian-equity research with visible specialist evidence, cross-framework ADK/CrewAI execution, risk-aware proposals and explicit human approval before paper-trade submission.

## Operating Context

The existing Python CLI analyzes RELIANCE, TCS, INFY, HDFCBANK and ICICIBANK from prepared datasets. Data refresh is separate. The interface must expose missing or stale data, fallbacks, errors and source provenance instead of presenting them as live model research.

## Capabilities and Constraints

- The Market Analyst migration to actual Google ADK and standard A2A communication with the CrewAI research crew is approved.
- Live states must come from execution events. Any replay or demonstration is labeled.
- Paper trading uses MegaBull and virtual funds only. Every submission requires an explicit user approval of the final order details. No test orders are authorized yet.
- Credentials stay in server-side ignored environment files; never in frontend bundles or trace payloads.
- Langfuse uses US Cloud; traces must identify KAIROS, the agent/framework, ticker, execution mode and environment.
- Existing datasets and research history must be preserved during restructuring and testing.
- Render Free is selected; the owner deferred account setup and deployment. No successful cloud deployment is claimed.

## Brand Commitments

KAIROS. The user requests a beautiful, professional interface with animations, illustrations and effects. The owner approved Evidence Atlas: a deep-blue shell, cool light workspace, Manrope typography and animated evidence handoffs. New research always fetches fresh evidence; no saved-data selector. NSE and BSE search preserve the listing exchange.

## Evidence on Hand

Source: `kairos/`; editable definitions: `kairos_config/`; current research data: `data/`. Earlier isolated checks exercised Pydantic reports, debate and offline proposals; that is not proof of profitable trading, current market data or a deployed service. TradingAgents is an architectural reference, not permission to adopt LangGraph.

## Product Principles

- Make every recommendation traceable to evidence and its timestamp.
- Separate research, review, user approval and paper execution.
- Treat missing data and model failures as visible product states.
- Keep the research task clear while making evaluator evidence easy to inspect.
- Use motion to explain agent transitions without obstructing reading or approval.
