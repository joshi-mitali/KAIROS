"""Evaluate a saved full research run without placing orders or inventing return metrics."""
import argparse
import json
from pathlib import Path
from kairos.schemas.analyst_reports import MarketAnalysisReport, SentimentAnalysisReport, NewsAnalysisReport, FundamentalsAnalysisReport, ResearchSynthesisVerdict
from kairos.schemas.trading_proposal import TradingProposal


def evaluate(result):
    reports=result['analyst_reports']
    models={'market':MarketAnalysisReport,'sentiment':SentimentAnalysisReport,'news':NewsAnalysisReport,'fundamentals':FundamentalsAnalysisReport}
    parsed={name:model.model_validate(reports[name]) for name,model in models.items()}
    verdict=ResearchSynthesisVerdict.model_validate(result['verdict'])
    proposal=TradingProposal.model_validate(result['trading_proposal'])
    aligned=all(report.ticker==result['ticker'] for report in [*parsed.values(),verdict,proposal])
    tools=result.get('adk_state',{}).get('market_tools',[])
    return {'application':'KAIROS','ticker':result['ticker'],'schema_validation':'PASS','ticker_alignment':'PASS' if aligned else 'FAIL',
            'runtime_seconds':round(result['latency_ms']/1000,2),'peak_process_memory_mb':result['memory_mb'],
            'market_mcp_tools':tools,'mcp_tool_requirement':'PASS' if len(set(tools))>=2 else 'NOT_EVIDENCED',
            'execution_modes':{**{name:report.execution_mode for name,report in parsed.items()},'debate':verdict.execution_mode,'proposal':proposal.execution_mode},
            'langfuse_trace_url':result.get('langfuse_trace_url'),'cost_usd':None,
            'cost_note':'Use measured Langfuse generation usage and provider pricing; missing cost is unknown, not zero.',
            'financial_quality':'Not evaluated: one workflow run cannot establish accuracy, calibration or investment returns.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('result',type=Path);args=parser.parse_args()
    print(json.dumps(evaluate(json.loads(args.result.read_text())),indent=2))
