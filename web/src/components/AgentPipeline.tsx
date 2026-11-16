import { useState } from 'react';
import { Activity, ArrowRight, ArrowUpRight, BarChart3, BookOpen, Check, CheckCircle2, ChevronDown, Circle, FileSearch, Fingerprint, GitBranch, Loader2, MessageSquareText, ShieldCheck, TrendingDown, TrendingUp, Wallet, AlertTriangle } from 'lucide-react';
import type { Run, RunEvent } from '../types';
const agents=[
 {key:'market',label:'Market analyst',framework:'Google ADK',icon:BarChart3,job:'Read price history and quotes through two MCP tools. Calculate indicators in Python.'},
 {key:'sentiment',label:'Sentiment analyst',framework:'Specialist',icon:MessageSquareText,job:'Review retail discussion, its sample size and source provenance.'},
 {key:'news',label:'News analyst',framework:'Specialist',icon:FileSearch,job:'Screen article text and explain catalysts and regulatory risks.'},
 {key:'fundamentals',label:'Fundamentals',framework:'Specialist',icon:BookOpen,job:'Assess reported financials, profitability and solvency.'},
 {key:'bull',label:'Bull researcher',framework:'CrewAI',icon:TrendingUp,job:'Build the upside case and respond to the Bear’s evidence.'},
 {key:'bear',label:'Bear researcher',framework:'CrewAI',icon:TrendingDown,job:'Challenge the upside case and identify downside risk.'},
 {key:'manager',label:'Research manager',framework:'CrewAI',icon:GitBranch,job:'Weigh both arguments and return a typed research verdict.'},
 {key:'trader',label:'Trader',framework:'Proposal',icon:Wallet,job:'Combine the verdict, risk preference and memory into an explained simulated proposal.'},
];
function keyFor(name:string){const value=(name||'').toLowerCase();return agents.find(a=>value.includes(a.key)||(a.key==='manager'&&value.includes('chief investment')))?.key;}
export default function AgentPipeline({events,run,onInspect}:{events:RunEvent[];run:Run|null;onInspect:()=>void}){
 const [selected,setSelected]=useState<string|null>(null),[expanded,setExpanded]=useState(false);
 const statuses:Record<string,string>={},outputs:Record<string,unknown>={};
 for(const event of events){const key=keyFor(event.payload.agent);if(!key)continue;
  if(event.type==='agent-started')statuses[key]='working';
  if(['agent-completed','debate-argument'].includes(event.type)){statuses[key]='complete';outputs[key]=event.payload.report||event.payload.thesis;}
  if(event.type==='agent-failed'){statuses[key]='failed';outputs[key]=event.payload.message;}
 }
 const refreshing=events.some(e=>e.type==='evidence-refresh-started')&&!events.some(e=>e.type==='agent-started')&&run?.status==='RUNNING';
 const latestRefresh=events.filter(e=>e.type.startsWith('evidence-')).at(-1);
 const sentimentDown=events.find(e=>e.type==='evidence-unavailable'&&e.payload.source==='Sentiment');
 const failed=['FAILED','INTERRUPTED'].includes(run?.status||'');
 if(failed)for(const key of Object.keys(statuses))if(statuses[key]==='working')statuses[key]='failed';
 const active=agents.find(a=>statuses[a.key]==='working'),bad=agents.find(a=>statuses[a.key]==='failed');
 const focused=agents.find(a=>a.key===selected)||active||bad||agents[0];
 const done=Object.values(statuses).filter(s=>s==='complete').length;
 const status=(key:string)=>statuses[key]||(failed?'blocked':'waiting');
 const labels:Record<string,string>={complete:'Complete',working:'Working',failed:'Failed',blocked:'Not reached',waiting:run?'Waiting':'Ready'};const label=(state:string)=>labels[state];
 const phases=[{name:'Gather',detail:'4 specialist reports',keys:['market','sentiment','news','fundamentals']},{name:'Debate',detail:'Bull ↔ Bear → Manager',keys:['bull','bear','manager']},{name:'Propose',detail:'Your approval follows',keys:['trader']}];
 return <section className="panel pipeline-panel" aria-label="Agent execution pipeline"><div className="section-heading"><div><h2>Research pipeline</h2><p>One evidence trail. Every handoff visible.</p></div><button className="text-button" onClick={onInspect}>Inspect evidence <ArrowUpRight size={15}/></button></div>
 <div className="phase-rail">{phases.map((phase,i)=>{const complete=phase.keys.every(k=>status(k)==='complete'),working=phase.keys.some(k=>status(k)==='working'),error=phase.keys.some(k=>status(k)==='failed');return <div className={`phase ${complete?'complete':working?'working':error?'failed':''}`} key={phase.name}><span className="phase-marker">{complete?<Check size={16}/>:working?<Activity size={16}/>:error?<AlertTriangle size={15}/>:<Circle size={10}/>}</span><div><strong>{phase.name}</strong><small>{phase.detail}</small></div>{i<2&&<span className="phase-connector"><ArrowRight size={17}/><small>{i===0?'A2A':'Typed verdict'}</small></span>}</div>;})}</div>
 <div className={`pipeline-focus ${bad?'failed':active?'working':''}`} aria-live="polite"><div className="focus-symbol">{active?<Loader2 className="spin" size={23}/>:bad?<AlertTriangle size={23}/>:run?.status==='COMPLETED'?<CheckCircle2 size={23}/>:<GitBranch size={23}/>}</div><div><strong>{refreshing?'Refreshing live evidence':active?active.label+' is working':bad?'Paused at '+bad.label:run?.status==='COMPLETED'?'Research complete':failed?'Research stopped before completion':'Ready when you are'}</strong><p>{refreshing?String(latestRefresh?.payload.source||'Contacting data providers')+' · collecting source dates before agents begin.':active?active.job:bad?'The workflow stopped here. Review the error before starting another run.':failed?(run?.error||'Review the execution feed and retry when sources recover.'):run?.status==='COMPLETED'?'Reports, debate and proposal are available in the evidence view.':'Choose a stock to follow its evidence through the pipeline.'}</p></div><span className="completion-count"><strong>{done}<small> / 8</small></strong><span>agents finished</span></span></div>
 <div className="pipeline-nodes">{agents.map((agent,i)=>{const Icon=agent.icon,state=status(agent.key);return <button key={agent.key} className={`pipeline-node ${state} ${selected===agent.key?'inspected':''}`} onClick={()=>{setSelected(agent.key);setExpanded(true);}} aria-expanded={expanded&&focused.key===agent.key}><span className="pipeline-node-icon"><Icon size={18}/>{state==='working'&&<span className="orbit-dot"/>}</span><span className="node-name"><strong>{agent.label}</strong><small>{agent.framework}</small></span><span className="node-state">{state==='complete'?<CheckCircle2 size={14}/>:state==='working'?<Loader2 className="spin" size={14}/>:state==='failed'?<AlertTriangle size={14}/>:<Circle size={9}/>} {label(state)}</span>{i<agents.length-1&&<span className={`node-link ${state==='complete'&&status(agents[i+1].key)==='working'?'transferring':''}`} aria-hidden="true"/>}</button>;})}</div>
 <div className="pipeline-inspector"><button className="inspector-toggle" onClick={()=>setExpanded(!expanded)} aria-expanded={expanded}><Fingerprint size={16}/><span>{focused.label} · {outputs[focused.key]?'Inspect output':'About this step'}</span><ChevronDown className={expanded?'rotated':''} size={16}/></button>{expanded&&<div className="inspector-body"><p>{focused.job}</p>{outputs[focused.key]?<pre>{JSON.stringify(outputs[focused.key],null,2)}</pre>:<span className="muted">No output recorded for this agent yet.</span>}</div>}</div>
 {sentimentDown&&<p className="quiet-note" role="status"><AlertTriangle size={16}/><span>Sentiment unavailable — Reddit unreachable. The run continues without retail sentiment; it is not treated as neutral.</span></p>}
 <div className="agent-panel-footer"><span><ShieldCheck size={14}/> Pydantic-validated handoffs</span><span><Activity size={14}/> Actual callbacks · no simulated progress</span></div></section>;
}
