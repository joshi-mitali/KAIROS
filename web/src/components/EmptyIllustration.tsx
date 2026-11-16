export default function EmptyIllustration({working=false}:{working?:boolean}) { return <svg className={`evidence-illustration ${working?'is-working':''}`} viewBox="0 0 280 140" role="img" aria-label={working?'Evidence is moving between research agents':'Four evidence sources connect to one reviewed result'}>
  <defs><pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="currentColor" opacity=".13"/></pattern></defs>
  <rect width="280" height="140" rx="16" fill="url(#dots)"/>
  {[25,55,85,115].map((y,i)=><g key={y}><path className="evidence-thread" d={`M63 ${y} C125 ${y},122 70,177 70`} fill="none" stroke="currentColor" opacity={.16+i*.08}/><rect x="30" y={y-8} width="32" height="16" rx="4" fill="var(--surface)" stroke="var(--line)"/><path d={`M38 ${y-2}h16M38 ${y+3}h10`} stroke="currentColor" opacity=".55"/></g>)}
  <rect x="177" y="45" width="67" height="50" rx="10" fill="var(--surface)" stroke="var(--line)"/><path d="m193 70 10 9 23-23" stroke="var(--positive)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
</svg>; }
