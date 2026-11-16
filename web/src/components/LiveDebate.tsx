import { useState } from 'react';
import { ArrowRight, MessageSquareText, Loader2, Scale, TrendingDown, TrendingUp, ChevronDown } from 'lucide-react';
import type {Data,Run,RunEvent} from '../types';
function role(value:string){const v=(value||'').toLowerCase();return v.includes('bull')?'Bull researcher':v.includes('bear')?'Bear researcher':v.includes('manager')||v.includes('chief investment')?'Research manager':null;}
function Argument({event,index}:{event:RunEvent;index:number}){
 const [raw,setRaw]=useState(false),name=role(event.payload.agent)||event.payload.agent;
 const output=event.payload.thesis as Data,up=name==='Bull researcher';
 const args=output?.primary_arguments||output?.key_decision_factors||[output?.summary||output?.synthesis_rationale].filter(Boolean);
 return <article className={`debate-turn ${up?'bull':name==='Bear researcher'?'bear':'manager'}`}><div className="debate-turn-header"><span className="speaker-icon">{up?<TrendingUp size={17}/>:name==='Bear researcher'?<TrendingDown size={17}/>:<Scale size={17}/>}</span><strong>{name}</strong><span>Contribution {index+1}</span><time>{new Date(event.created*1000).toLocaleTimeString('en-IN')}</time></div><div className="debate-argument">{args?.length?<ul>{args.map((argument:string,i:number)=><li key={i}>{argument}</li>)}</ul>:<p>Structured contribution received. Open details to inspect it.</p>}{output?.counter_arguments?.length>0&&<div><strong>Response to the opposing case</strong><ul>{output.counter_arguments.map((s:string,i:number)=><li key={i}>{s}</li>)}</ul></div>}{output?.recommendation&&<p className="debate-decision">Verdict: <strong>{output.recommendation}</strong> · {output.conviction}</p>}<button className="text-button" onClick={()=>setRaw(!raw)} aria-expanded={raw}>Structured output <ChevronDown size={13}/></button>{raw&&<pre>{JSON.stringify(output,null,2)}</pre>}</div></article>;
}
export default function LiveDebate({events,run}:{events:RunEvent[];run:Run|null}){
 const argumentsReceived=events.filter(e=>e.type==='debate-argument');
 const starts=events.filter(e=>e.type==='agent-started'&&role(e.payload.agent));
 const latest=starts.at(-1),lastArgument=argumentsReceived.at(-1);
 const active=run?.status==='RUNNING'&&latest&&(!lastArgument||latest.id>lastArgument.id)?role(latest.payload.agent):null;
 const streams=events.filter(e=>e.type==='debate-stream'&&(!latest||e.id>latest.id));
 const text=streams.map(e=>e.payload.text).join('');
 const verdict=events.filter(e=>e.type==='debate-completed').at(-1)?.payload.verdict||run?.result?.verdict;
 const failed=['FAILED','INTERRUPTED'].includes(run?.status||'');
 return <section className="panel live-debate" aria-label="Live research debate"><div className="section-heading"><div><h2>Inside the debate</h2><p>Bull and Bear make their case. The manager weighs the evidence.</p></div><span className={`debate-status ${active?'active':''}`}>{active?<><Loader2 className="spin" size={13}/> Live contribution</>:argumentsReceived.length?`${argumentsReceived.length} contributions`:'Awaiting evidence'}</span></div>
 {argumentsReceived.length?<div className="debate-transcript">{argumentsReceived.map((event,i)=><Argument key={event.id} event={event} index={i}/>)}</div>:<div className="debate-empty"><svg viewBox="0 0 220 90" role="img" aria-label="Two opposing evidence paths meet at a reviewed verdict"><path d="M35 25H70Q90 25 110 45Q130 65 150 65H185M35 65H70Q90 65 110 45Q130 25 150 25H185" fill="none" stroke="currentColor" strokeWidth="1.5"/><circle cx="35" cy="25" r="6" fill="var(--positive)"/><circle cx="35" cy="65" r="6" fill="var(--negative)"/><rect x="96" y="31" width="28" height="28" rx="7" fill="var(--surface)" stroke="currentColor"/><path d="m103 45 5 5 10-11" stroke="currentColor" fill="none"/></svg><div><strong>{failed?'The debate has not started.':'Two perspectives. One reviewed decision.'}</strong><p>{failed?'Resolve the failed evidence step and start a fresh run.':'Contributions appear here after the specialist reports arrive. Select an agent above to inspect its current output.'}</p></div></div>}
 {active&&<div className="debate-stream" aria-live="polite"><div><Loader2 size={16} className="spin"/><strong>{active} is responding</strong><span>Draft model output · not yet validated</span></div>{text?<pre>{text.slice(-12000)}</pre>:<p>Waiting for response text from the model. No contribution has been invented.</p>}</div>}
 {verdict&&<div className="debate-verdict"><Scale size={20}/><div><strong>Manager’s verdict · {verdict.recommendation}</strong><p>{verdict.synthesis_rationale}</p><span>{verdict.execution_mode==='LIVE_CREWAI_LLM'?'Live CrewAI debate':'Rule-based fallback'} · Conviction is uncalibrated.</span></div><ArrowRight size={17}/></div>}
 <div className="agent-panel-footer"><span><MessageSquareText size={14}/> Contributions and streamed drafts come from execution events.</span><span>Drafts remain unvalidated until the task completes.</span></div></section>;
}
