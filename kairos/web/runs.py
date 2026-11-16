"""Durable research results and append-only UI events; one worker limits API bursts."""
import json
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kairos.observability.callbacks import CallbackManager
from kairos.observability.langfuse_tracing import flush_traces, mask_data
from kairos.phase2_orchestrator import Phase2Orchestrator


def encode(value):
    return json.dumps(mask_data(value), default=str)


def data_gaps(provenance):
    """Short labels for evidence that returned nothing; supplementary labels use the source name."""
    gaps=[]
    if (provenance["sources"].get("sentiment") or {}).get("status") in ("UNAVAILABLE","NO_RECENT_DISCUSSION"):
        gaps.append("Sentiment")
    gaps+=[r["name"] for r in provenance["sources"].get("supplementary") or [] if r.get("status") in ("unavailable","failed")]
    return gaps


class RunStore:
    def __init__(self, path: Path, data_dir: Path):
        self.path, self.data_dir = path, data_dir
        path.parent.mkdir(parents=True, exist_ok=True)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kairos-research")
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, ticker TEXT NOT NULL,
                    risk TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS research_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    type TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL);
            ''')
            # In-flight Python work cannot survive a process restart. Never show it as running forever.
            db.execute("UPDATE research_runs SET status='INTERRUPTED',error='Server restarted. Start a new run; completed evidence remains available.' WHERE status IN ('QUEUED','RUNNING')")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def emit(self, run_id, event_type, payload):
        db = self.connect()  # one connection per call, so any thread may emit; closed explicitly (the with-block only commits)
        try:
            with db:
                db.execute("INSERT INTO research_events(run_id,type,created,payload) VALUES(?,?,?,?)", (run_id,event_type,time.time(),encode(payload)))
        finally:
            db.close()

    def create(self, owner, ticker, risk, source):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM research_runs WHERE status IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                raise ValueError("A research run is already active. Wait for it to finish before starting another.")
            db.execute("INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?)",(run_id,owner,ticker,risk,source,"QUEUED",time.time(),None,None))
        self.emit(run_id,"run-queued",{"ticker":ticker,"risk":risk,"source":source})
        self.worker.submit(self.execute,run_id,ticker,risk,source)
        return run_id

    def execute(self, run_id, ticker, risk, source):
        with self.connect() as db:
            db.execute("UPDATE research_runs SET status='RUNNING' WHERE id=?",(run_id,))
        self.emit(run_id,"run-started",{"ticker":ticker,"source":source})
        try:
            from kairos.pipeline.live_research import refresh_research_evidence
            evidence_dir = self.path.parent / 'evidence' / run_id
            provenance = refresh_research_evidence(ticker,evidence_dir,lambda kind,payload:self.emit(run_id,kind,payload))
            callbacks=CallbackManager([EventCallback(self,run_id)])
            orchestrator=Phase2Orchestrator(data_dir=str(evidence_dir),callback_manager=callbacks)
            orchestrator.market_analyst.source=source
            result=orchestrator.analyze_ticker(ticker,risk)
            result["provenance"]=provenance
            result["adk_state"]=orchestrator.market_analyst.last_state
            # The root trace URL is also captured by analyze-equity's decorator.
            with self.connect() as db:
                db.execute("UPDATE research_runs SET status='COMPLETED',result=? WHERE id=?",(encode(result),run_id))
            self.emit(run_id,"run-completed",{"ticker":ticker})
        except Exception as exc:
            message=mask_data(str(exc))
            with self.connect() as db:
                db.execute("UPDATE research_runs SET status='FAILED',error=? WHERE id=?",(message,run_id))
            self.emit(run_id,"run-failed",{"message":message})
        finally:
            flush_traces()

    def get(self, run_id, owner):
        with self.connect() as db:
            row=db.execute("SELECT * FROM research_runs WHERE id=? AND owner=?",(run_id,owner)).fetchone()
        if row is None:
            return None
        result=dict(row);result.pop("owner")
        result["result"]=json.loads(result["result"]) if result["result"] else None
        return result

    def list(self, owner):
        with self.connect() as db:
            rows=db.execute("""SELECT id,ticker,risk,source,status,created,error,
                json_extract(result,'$.verdict.recommendation') AS recommendation,
                json_extract(result,'$.trading_proposal.direction') AS direction,
                json_extract(result,'$.provenance') AS provenance,
                (SELECT MAX(created) FROM research_events e WHERE e.run_id=research_runs.id AND e.type IN ('run-completed','run-failed')) AS finished
                FROM research_runs WHERE owner=? ORDER BY created DESC LIMIT 100""",(owner,)).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            provenance=json.loads(item.pop("provenance")) if item["provenance"] else None
            finished=item.pop("finished")
            item["duration_s"]=round(finished-item["created"],1) if finished else None
            item["data_gaps"]=data_gaps(provenance) if provenance else None
            out.append(item)
        return out

    def events(self, run_id, after=0):
        with self.connect() as db:
            rows=db.execute("SELECT * FROM research_events WHERE run_id=? AND id>? ORDER BY id LIMIT 200",(run_id,after)).fetchall()
        return [{"id":row["id"],"type":row["type"],"created":row["created"],"payload":json.loads(row["payload"])} for row in rows]


class EventCallback:
    def __init__(self, store, run_id):
        self.store,self.run_id=store,run_id

    def send(self, kind, **payload):
        self.store.emit(self.run_id,kind,payload)

    def on_analyst_start(self, agent_name,ticker,trace_id):
        self.send("agent-started",agent=agent_name,ticker=ticker,trace_id=trace_id)

    def on_analyst_complete(self,agent_name,ticker,report,latency_ms,trace_id):
        self.send("agent-completed",agent=agent_name,ticker=ticker,report=report,latency_ms=latency_ms)

    def on_agent_event(self,agent_name,ticker,event,trace_id):
        self.send("agent-state",agent=agent_name,ticker=ticker,event=event)

    def on_debate_start(self,ticker,trace_id):
        self.send("agent-started",agent="crewai.research_crew",ticker=ticker)

    def on_thesis_generated(self,researcher_role,ticker,thesis,trace_id):
        self.send("debate-argument",agent=researcher_role,ticker=ticker,thesis=thesis)

    def on_research_task(self,agent,output,trace_id):
        self.send("debate-argument",agent=agent,thesis=output)

    def on_research_task_start(self,agent,trace_id):
        self.send("agent-started",agent=agent,trace_id=trace_id)

    def on_research_stream(self,agent,task_id,text,trace_id):
        self.send("debate-stream",agent=agent,task_id=task_id,text=text)

    def on_debate_transcript(self,ticker,rounds,verdict,trace_id):
        self.send("debate-completed",ticker=ticker,rounds=rounds,verdict=verdict)

    def on_verdict_reached(self,verdict,trace_id):
        self.send("agent-completed",agent="crewai.research_manager",report=verdict)

    def on_guardrail_result(self,result,trace_id):
        self.send("guardrail-result",result=result)

    def on_error(self,agent_name,error,trace_id):
        self.send("agent-failed",agent=agent_name,message=str(error))
