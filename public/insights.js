/* Opt-in, account-scoped browser history. No credentials are stored here. */
const WellnessTools = (() => {
  const schema = 1;
  const defaults = {sleep_hours:7.5, steps:8000, cardio_minutes:150, strength_days:2};
  const bounds = {sleep_hours:[4,12], steps:[500,40000], cardio_minutes:[0,1500], strength_days:[0,7]};
  function snapshot(data) {
    return {schema, as_of:data.window?.end_exclusive, observed_at:data.config?.last_synced || data.last_synced,
      model:data.model_version, source:data.data_source, age:data.chronological_age,
      manual_lean_pct:data.config?.manual_lean_pct ?? null, score:data.overall_score,
      wellness_age:data.biological_age, pace:data.pace_of_aging,
      pillars:(data.pillars || []).map(p=>({id:p.id, baseline:p.baseline_value, recent:p.recent_value,
        unit:p.unit, score:p.score_0_100, available:p.status!=='no_data', days:p.baseline_days ?? p.observation_days ?? 0,
        recent_days:p.recent_days ?? p.calendar?.filter(d=>d.recorded).length ?? 0,
        latest:p.latest_observation, baseline_source:p.baseline_source || 'Recorded data', recent_source:p.recent_source || 'Recorded data'}))};
  }
  function comparable(a,b) {
    if (!a || !b || a.schema!==schema || b.schema!==schema || a.source!=='fitbit_live' || b.source!=='fitbit_live') return 'Two saved live syncs are needed.';
    if(a.as_of===b.as_of) return 'Compare syncs from different days.';
    if(a.model!==b.model) return 'Model versions differ.';
    if(a.age!==b.age || a.manual_lean_pct!==b.manual_lean_pct) return 'Profile settings differ.';
    const active=x=>x.pillars.filter(p=>p.available).map(p=>p.id).sort().join('|');
    if(active(a)!==active(b)) return 'Available pillars differ.';
    for(const p of a.pillars.filter(p=>p.available)) {
      const q=b.pillars.find(q=>q.id===p.id);
      if(p.baseline_source!==q.baseline_source || p.recent_source!==q.recent_source) return 'Measurement sources differ.';
      if(Math.abs(p.days-q.days)>Math.max(2,Math.max(p.days,q.days)*.1) || Math.abs(p.recent_days-q.recent_days)>2) return 'Data coverage differs substantially.';
    }
    return null;
  }
  function validateGoals(goals) {
    for(const [key,[min,max]] of Object.entries(bounds)) {
      if(!Number.isFinite(goals[key]) || goals[key]<min || goals[key]>max) throw new Error(`Check ${key.replaceAll('_',' ')}: allowed ${min}–${max}.`);
    }
    return goals;
  }
  function cell(value) {
    let s=value==null?'':String(value);
    if(/^[\s]*[=+\-@]/.test(s)) s="'"+s;
    return '"'+s.replaceAll('"','""')+'"';
  }
  function csv(snapshots) {
    const rows=[['as_of','recorded_at','source','model','pillar','baseline','recent','unit','app_score','baseline_days','recent_days','latest_observation']];
    for(const s of snapshots) for(const p of s.pillars) rows.push([s.as_of,s.observed_at,s.source,s.model,p.id,p.baseline,p.recent,p.unit,p.score,p.days,p.recent_days,p.latest]);
    return rows.map(r=>r.map(cell).join(',')).join('\r\n');
  }
  return {snapshot,comparable,validateGoals,csv,defaults,schema};
})();

function localKey(suffix) {
  const cfg=currentDashboard?.config;
  const id=cfg?.connected ? cfg.history_id || cfg.cache_id : 'sample';
  return id ? `healthspan_${suffix}_v1_${id}` : null;
}
function readLocal(suffix,fallback) {
  try {const key=localKey(suffix);return key ? JSON.parse(localStorage.getItem(key) || 'null') ?? fallback : fallback;} catch {return fallback;}
}
function writeLocal(suffix,value) {
  const key=localKey(suffix);if(!key) throw new Error('Sync your account first.');
  localStorage.setItem(key,JSON.stringify(value));
}
function historyRows() {
  const rows=readLocal('history',[]);
  return Array.isArray(rows) ? rows.filter(r=>r.schema===WellnessTools.schema && Array.isArray(r.pillars)).slice(-180) : [];
}
function saveSnapshot(data) {
  if(data.data_source!=='fitbit_live' || !data.config?.connected || !readLocal('history_enabled',false)) return;
  const entry=WellnessTools.snapshot(data);
  const rows=historyRows().filter(r=>!(r.as_of===entry.as_of && r.model===entry.model));
  rows.push(entry);rows.sort((a,b)=>(a.as_of||'').localeCompare(b.as_of||''));
  writeLocal('history',rows.slice(-180));
}
function renderInsights(data) {
  const connected=!!data.config?.connected && data.data_source==='fitbit_live';
  $('saveHistory').disabled=!connected;
  $('saveHistory').checked=connected && !!readLocal('history_enabled',false);
  const goals={...WellnessTools.defaults,...readLocal('goals',{})};
  for(const key of Object.keys(WellnessTools.defaults)) $('goal_'+key).value=goals[key];
  $('goalProgress').replaceChildren();
  const labels={sleep_hours:'Sleep hours/night',steps:'Steps/day',cardio_minutes:'Moderate-equivalent min/week',strength_days:'Logged strength days/week'};
  for(const [key,label] of Object.entries(labels)) {
    const val=data.goal_metrics?.[key];const row=document.createElement('p');
    row.textContent=`${label}: ${val==null?'Unavailable':val} / goal ${goals[key]}${val!=null ? (key==='sleep_hours' ? (Math.abs(val-goals[key])<=.5?' · Within 30 minutes of your goal':val>goals[key]?' · Above your goal':' · Below your goal') : val>=goals[key]?' · Goal reached':' · Below your goal') : ''}`;
    $('goalProgress').append(row);
  }
  const rows=connected ? historyRows() : [];
  $('historyRows').replaceChildren();
  for(const entry of rows.slice(-10).reverse()) {
    const tr=document.createElement('tr');
    for(const value of [entry.as_of,entry.score??'—',entry.wellness_age??'—',`${entry.pillars.filter(p=>p.available).length}/9`]) {
      const td=document.createElement('td');td.textContent=value;tr.append(td);
    }
    $('historyRows').append(tr);
  }
  const current=rows.at(-1), previous=rows.slice(0,-1).reverse().find(r=>r.as_of!==current?.as_of);
  const reason=WellnessTools.comparable(current,previous);
  $('historyComparison').textContent=reason || (current.score!=null && previous.score!=null ?
    `App score change since ${previous.as_of}: ${(current.score-previous.score).toFixed(1)} points. Same model and similar coverage; association does not establish health improvement.` : 'Comparable syncs saved; no overall score available.');
  $('historyEmpty').hidden=rows.length>0;
  $('historyPrivacy').textContent=connected ? 'Optional history stays in this browser, up to 180 dated snapshots. It is not encrypted at rest and is readable by someone with access to this browser profile. Disconnect or Clear saved history deletes it for this account.' : 'Connect and sync to save real snapshots. Sample previews are never saved as health history.';
}
function downloadExport(format) {
  if(!currentDashboard) return;
  const current=WellnessTools.snapshot(currentDashboard);
  const saved=currentDashboard.config?.connected ? historyRows() : [];
  const rows=saved.filter(r=>!(r.as_of===current.as_of && r.model===current.model));rows.push(current);
  const content=format==='csv' ? WellnessTools.csv(rows) : JSON.stringify({export_schema:1,notice:'Experimental wellness data, not a validated biological clock.',snapshots:rows},null,2);
  const blob=new Blob([content],{type:format==='csv'?'text/csv;charset=utf-8':'application/json'});
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;
  a.download=`healthspan-${current.source==='sample_preview'?'SAMPLE-':''}${current.as_of||'export'}.${format}`;a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
