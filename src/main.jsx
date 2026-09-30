import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Archive, BrainCircuit, CirclePlus, SearchCheck, Zap } from 'lucide-react'
import './styles.css'

const api = async (path, options) => {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Something went wrong')
  return response.status === 204 ? null : response.json()
}

const priorityClass = (priority) => priority.toLowerCase()
const formatTime = (value) => new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))

function TeamSelect({ teams, selected, onChange }) {
  return <label className="team-select">Viewing as
    <select value={selected ?? 'all'} onChange={(e) => onChange(e.target.value === 'all' ? null : Number(e.target.value))}>
      <option value="all">ADMIN</option>
      {teams.filter(team => team.name !== 'ADMIN').map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
    </select>
  </label>
}

function NewIncident({ applications, onCreated, onCancel }) {
  const [form, setForm] = useState({ title: '', application_id: applications[0]?.id ?? '', priority: 'Medium', initial_description: '' })
  const [error, setError] = useState('')
  const change = (key, value) => setForm({ ...form, [key]: value })
  const submit = async (event) => {
    event.preventDefault(); setError('')
    if (!form.title.trim()) return setError('Enter an incident title so the ticket can be identified and matched with similar incidents later.')
    if (!form.initial_description.trim()) return setError('Enter the initial issue description before creating the incident.')
    try { await onCreated({ ...form, application_id: Number(form.application_id) }) } catch (e) { setError(e.message) }
  }
  return <form className="new-incident" onSubmit={submit} noValidate>
    <div className="form-heading"><div><p className="eyebrow">New incident</p><h2>Create an incident</h2></div><button type="button" className="icon-button" onClick={onCancel}>×</button></div>
    <label>Incident title<input value={form.title} onChange={e => change('title', e.target.value)} placeholder="Example: File delivery failed" /></label>
    <div className="form-grid"><label>Application<select value={form.application_id} onChange={e => change('application_id', e.target.value)}>{applications.map(app => <option key={app.id} value={app.id}>{app.name} · {app.primary_team_name}</option>)}</select></label>
      <label>Priority<select value={form.priority} onChange={e => change('priority', e.target.value)}>{['Low', 'Medium', 'High', 'Critical'].map(p => <option key={p}>{p}</option>)}</select></label></div>
    <label>Initial description<textarea value={form.initial_description} onChange={e => change('initial_description', e.target.value)} placeholder="Describe the initial symptom, alert, error, or observed issue." rows="7" /></label>
    {error && <p className="form-error">{error}</p>}
    <div className="form-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary">Create incident</button></div>
  </form>
}

function TicketToolbar({ incident, activeTeam, onChooseAction }) {
  const available = incident.status === 'Closed'
    ? [['reopen', 'Reopen']]
    : incident.status === 'Acknowledged'
      ? [['update', 'Update'], ['transfer', 'Transfer'], ['close', 'Close']]
      : [['open', 'Solving / Take into account']]
  const canOperate = activeTeam === null ? incident.status !== 'Open' && incident.status !== 'Transferred' : activeTeam === incident.current_team_id
  return <div className="ticket-toolbar">
    <button type="button" className="tool-button">‹ Previous</button>
    <button type="button" className="tool-button">Next ›</button>
    <span className="tool-divider" />
    <button type="button" className="tool-button">↻ Refresh</button>
    {canOperate && available.map(([action, label]) => <button key={action} type="button" className={`tool-button ${action === 'close' ? 'close-tool' : ''}`} onClick={() => onChooseAction(action)}>{label}</button>)}
  </div>
}

function CommentComposer({ incident, teams, activeTeam, onAction, requestedAction, onActionChange }) {
  const defaultAction = incident.status === 'Closed' ? 'reopen' : incident.status === 'Acknowledged' ? 'update' : 'open'
  const [action, setAction] = useState(defaultAction)
  const [body, setBody] = useState('')
  const [destination, setDestination] = useState('')
  const [error, setError] = useState('')
  const selectedTeam = activeTeam ?? teams.find(team => team.name === 'ADMIN')?.id
  useEffect(() => { setAction(incident.status === 'Closed' ? 'reopen' : incident.status === 'Acknowledged' ? 'update' : 'open'); setBody(''); setError('') }, [incident.id, incident.status])
  useEffect(() => { if (requestedAction) setAction(requestedAction) }, [requestedAction])
  const labels = { open: 'OPEN', update: 'Update', transfer: 'Transfer', close: 'Close', reopen: 'Reopen' }
  const submit = async (event) => {
    event.preventDefault(); setError('')
    if (!body.trim()) return setError(`Add a comment before recording ${labels[action]}. This keeps the incident timeline useful for the next team.`)
    if (action === 'transfer' && !destination) return setError('Choose the receiving team before recording this transfer.')
    try {
      await onAction({ action, team_id: selectedTeam, body, destination_team_id: destination ? Number(destination) : null })
      setBody(''); setDestination('')
    } catch (e) { setError(e.message) }
  }
  const selectAction = (value) => { setAction(value); onActionChange?.(value) }
  if (incident.status === 'Transferred') {
    if (activeTeam === null) return <section className="admin-notice"><strong>This incident is awaiting {incident.current_team_name}.</strong><span>It remains Transferred until {incident.current_team_name} adds the OPEN / TIA comment. ADMIN cannot take action before then.</span></section>
    if (activeTeam !== incident.current_team_id) return <section className="admin-notice"><strong>This incident was transferred to {incident.current_team_name}.</strong><span>Switch to that team; it must add the OPEN / TIA comment before any other action is available.</span></section>
  }
  if (activeTeam !== null && activeTeam !== incident.current_team_id) return <section className="admin-notice"><strong>This incident belongs to {incident.current_team_name}.</strong><span>Switch to that team to add an incident comment or take an action.</span></section>
  if (activeTeam === null && incident.status === 'Open') return <section className="admin-notice"><strong>ADMIN cannot take an incident into account.</strong><span>Switch to {incident.current_team_name}; that team must add the OPEN / TIA comment before ADMIN can update, transfer, or close it.</span></section>
  return <form className="composer" onSubmit={submit} noValidate>
    <div className="composer-row"><label>Action<select value={action} onChange={e => selectAction(e.target.value)}>
      {(incident.status === 'Open' || incident.status === 'Transferred') && activeTeam !== null && <option value="open">OPEN / Take into account</option>}
      {incident.status === 'Acknowledged' && <><option value="update">Update</option><option value="transfer">Transfer</option><option value="close">Close</option></>}
      {incident.status === 'Closed' && <option value="reopen">Reopen</option>}
    </select></label>
      <span className="acting-team">Posting as <strong>{teams.find(t => t.id === selectedTeam)?.name}</strong></span>
    </div>
    {action === 'transfer' && <label>Receiving team<select value={destination} onChange={e => setDestination(e.target.value)}><option value="">Choose team</option>{teams.filter(team => team.id !== incident.current_team_id && team.name !== 'ADMIN').map(team => <option key={team.id} value={team.id}>{team.name}</option>)}</select></label>}
    <label>{action === 'close' ? 'Final closing comments' : 'Comment'}<textarea value={body} onChange={e => setBody(e.target.value)} rows={action === 'close' ? 6 : 3} placeholder={action === 'close' ? 'Cause:\n\nImpact:\n\nActions:' : action === 'open' ? 'Taking into account.' : action === 'reopen' ? 'Explain why this incident is being reopened.' : action === 'transfer' ? 'Explain why this incident is being transferred.' : 'Add a clear update.'} /></label>
    {error && <p className="form-error">{error}</p>}
    <div className="composer-footer"><span>Comments cannot be edited after submission.</span><button className="button primary">{labels[action]}</button></div>
  </form>
}

function Timeline({ comments }) {
  return <section className="timeline">
    {comments.map((comment) => <article className="comment" key={comment.id}>
      <header><time>{formatTime(comment.created_at)}</time><span>{comment.team_name}</span><strong>{comment.action}</strong></header>
      <p>{comment.body}</p>
    </article>)}
  </section>
}

function Evidence({ label, value }) {
  return value ? <div className="evidence-row"><b>{label}</b><span>{value}</span></div> : null
}

function Recommendation({ recommendation, minimized, onToggle }) {
  const [closest, ...alternatives] = recommendation?.matches || []
  return <aside className={`recommendation ${minimized ? 'minimized' : ''}`}>
    <div className="recommendation-head"><div><p className="eyebrow">AI support</p><h3>{recommendation?.mode === 'historical' ? 'Historical evidence' : 'Suggested first checks'}</h3></div><button className="icon-button" onClick={onToggle}>{minimized ? '↗' : '−'}</button></div>
    {!minimized && <>{recommendation?.mode === 'historical' && <p className="retrieval-label">{recommendation.retrieval_type || 'Exact title'} · {recommendation.level}</p>}
      <p className="recommendation-summary">{recommendation?.summary || 'Searching closed-incident knowledge and preparing grounded guidance…'}</p>
      {recommendation?.suggested_checks?.length > 0 && <section className="suggested-checks"><p>Start here</p><ol>{recommendation.suggested_checks.map((check, index) => <li key={index}>{check}</li>)}</ol></section>}
      {closest && <div className="matches"><p>Closest closed incident</p><div className="match"><strong>INC-{String(closest.id).padStart(4, '0')} · {closest.application_name}</strong><em>{closest.title}</em><Evidence label="Confirmed cause" value={closest.cause} /><Evidence label="What resolved it" value={closest.actions} /><Evidence label="Log evidence" value={closest.log_evidence} /></div>{alternatives.length > 0 && <><p className="alternative-label">Other possible patterns — check separately</p>{alternatives.map(match => <div className="match alternative" key={match.id}><strong>INC-{String(match.id).padStart(4, '0')} · {match.application_name}</strong><em>{match.title}</em><Evidence label="Different cause" value={match.cause} /><Evidence label="Previous resolution" value={match.actions} /></div>)}</>}</div>}
      <p className="advisory">Suggestions are advisory. Validate all actions before making changes.</p></>}
  </aside>
}

function App() {
  const [teams, setTeams] = useState([])
  const [applications, setApplications] = useState([])
  const [activeTeam, setActiveTeam] = useState(null)
  const [incidents, setIncidents] = useState([])
  const [selected, setSelected] = useState(null)
  const [recommendation, setRecommendation] = useState(null)
  const [newForm, setNewForm] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const [preferredAction, setPreferredAction] = useState(null)
  const [queueMode, setQueueMode] = useState('active')
  const [filters, setFilters] = useState({ query: '', application: 'all', priority: 'all', status: 'all' })
  const [loading, setLoading] = useState(true)
  const refreshList = async (team = activeTeam) => setIncidents(await api(`/incidents${team ? `?team_id=${team}` : ''}`))
  useEffect(() => { Promise.all([api('/teams'), api('/applications')]).then(([t, a]) => { setTeams(t); setApplications(a) }).finally(() => setLoading(false)) }, [])
  useEffect(() => { if (!loading) { refreshList().catch(console.error); setSelected(null) } }, [activeTeam, loading])
  const openIncident = async (id) => { const detail = await api(`/incidents/${id}`); setSelected(detail); setRecommendation(null); setMinimized(false); setPreferredAction(null); const loadGuidance = async () => { const guidance = await api(`/incidents/${id}/recommendation?wait=false`); setRecommendation(guidance); if (guidance.mode === 'pending') setTimeout(() => loadGuidance().catch(console.error), 3500) }; loadGuidance().catch(console.error) }
  const createIncident = async (payload) => { const created = await api('/incidents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); setNewForm(false); await refreshList(); await openIncident(created.id) }
  const act = async (payload) => { await api(`/incidents/${selected.id}/actions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); await refreshList(); await openIncident(selected.id) }
  const counts = useMemo(() => ({ open: incidents.filter(i => i.status !== 'Closed').length, critical: incidents.filter(i => i.priority === 'Critical' && i.status !== 'Closed').length, closed: incidents.filter(i => i.status === 'Closed').length }), [incidents])
  const displayedIncidents = useMemo(() => incidents.filter(incident => {
    if (queueMode === 'active' && incident.status === 'Closed') return false
    if (queueMode === 'closed' && incident.status !== 'Closed') return false
    if (queueMode !== 'search') return true
    if (filters.application !== 'all' && incident.application_id !== Number(filters.application)) return false
    if (filters.priority !== 'all' && incident.priority !== filters.priority) return false
    if (filters.status !== 'all' && incident.status !== filters.status) return false
    const query = filters.query.trim().toLowerCase()
    return !query || `inc-${String(incident.id).padStart(4, '0')} ${incident.title} ${incident.application_name}`.toLowerCase().includes(query)
  }), [incidents, queueMode, filters])
  const updateFilter = (key, value) => setFilters(current => ({ ...current, [key]: value }))
  if (loading) return <main className="loading">Loading Incident Desk…</main>
  return <main className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><BrainCircuit size={23} strokeWidth={1.8} /></div><div className="brand-copy"><strong>SupportAI</strong><span>Broken again? We’ve seen it before.</span></div></div><div className="compact-project-message"><strong>A project by Jayesh Vinayak Dhevarshetty</strong><span>AI-powered production support that turns closed-incident evidence into faster, grounded troubleshooting.</span></div><div className="top-actions"><TeamSelect teams={teams} selected={activeTeam} onChange={setActiveTeam} /><button className="button primary" onClick={() => setNewForm(true)}><CirclePlus size={16} /> New incident</button></div></header>
    <section className={`workspace ${selected || newForm ? 'detail-mode' : 'list-mode'}`}>
      <aside className="queue"><div className="queue-head"><div><p className="eyebrow">{activeTeam ? 'Assignment group' : 'ADMIN workspace'}</p><h1>{queueMode === 'active' ? <><Zap size={19} /> Active incidents</> : queueMode === 'closed' ? <><Archive size={19} /> Closed incidents</> : <><SearchCheck size={19} /> Search incidents</>}</h1></div><span className="incident-count">{queueMode === 'closed' ? counts.closed : queueMode === 'active' ? counts.open : incidents.length}</span></div>
        <div className="queue-stats"><button className={queueMode === 'active' ? 'selected-stat' : ''} onClick={() => setQueueMode('active')}><strong>{counts.open}</strong> active</button><span><strong>{counts.critical}</strong> critical</span><button className={queueMode === 'closed' ? 'selected-stat' : ''} onClick={() => setQueueMode('closed')}><strong>{counts.closed}</strong> closed</button><button className={queueMode === 'search' ? 'selected-stat search-switch' : 'search-switch'} onClick={() => setQueueMode('search')}>⌕ Search incidents</button></div>
        {queueMode === 'search' && <div className="queue-filters"><input value={filters.query} onChange={e => updateFilter('query', e.target.value)} placeholder="Search ID, title, application" /><div><select value={filters.application} onChange={e => updateFilter('application', e.target.value)}><option value="all">All applications</option>{applications.map(app => <option key={app.id} value={app.id}>{app.name}</option>)}</select><select value={filters.priority} onChange={e => updateFilter('priority', e.target.value)}><option value="all">All priorities</option>{['Low', 'Medium', 'High', 'Critical'].map(priority => <option key={priority}>{priority}</option>)}</select><select value={filters.status} onChange={e => updateFilter('status', e.target.value)}><option value="all">All states</option><option value="Open">New</option><option value="Acknowledged">Open / TIA / transferred</option><option value="Closed">Closed</option></select></div></div>}
        <div className="queue-table"><div className="queue-columns"><span>□</span><span>Incident</span><span>State</span><span>Priority</span><span>Description</span><span>App</span></div>
          <div className="incident-list">{displayedIncidents.length === 0 ? <p className="empty-list">{queueMode === 'closed' ? 'No closed incidents in this view.' : queueMode === 'search' ? 'No incidents match your search.' : 'No active incidents in this view.'}</p> : displayedIncidents.map(incident => <button key={incident.id} className={`incident-row ${selected?.id === incident.id ? 'selected' : ''}`} onClick={() => openIncident(incident.id)}><span className="row-check">□</span><span className="incident-id">INC-{String(incident.id).padStart(4, '0')}</span><span className="row-state">{incident.status === 'Acknowledged' ? 'OPEN' : incident.status.toUpperCase()}</span><span className={`priority ${priorityClass(incident.priority)}`}>{incident.priority}</span><strong>{incident.title}</strong><span className="row-app">{incident.application_name}</span></button>)}</div></div>
      </aside>
      <section className="content">{newForm ? <NewIncident applications={applications} onCreated={createIncident} onCancel={() => setNewForm(false)} /> : selected ? <section className="ticket-window">
        <header className="ticket-titlebar"><span>{selected.current_team_name} · Incident Queue</span><strong>INC-{String(selected.id).padStart(4, '0')} · {selected.title}</strong><button className="icon-button" onClick={() => setSelected(null)}>×</button></header>
        <TicketToolbar incident={selected} activeTeam={activeTeam} onChooseAction={setPreferredAction} />
        <section className="incident-details">
          <div className="detail-field"><span>Incident number</span><strong>INC-{String(selected.id).padStart(4, '0')}</strong></div>
          <div className="detail-field"><span>Application</span><strong>{selected.application_name}</strong></div>
          <div className="detail-field"><span>Assigned team</span><strong>{selected.current_team_name}</strong></div>
          <div className="detail-field"><span>Status</span><strong>{selected.status}</strong></div>
          <div className="detail-field"><span>Priority</span><strong className={`priority ${priorityClass(selected.priority)}`}>{selected.priority}</strong></div>
          <div className="detail-field"><span>Created</span><strong>{formatTime(selected.created_at)}</strong></div>
          <div className="detail-field description-field"><span>Initial description</span><strong>{selected.initial_description}</strong></div>
        </section>
        <nav className="ticket-tabs"><button className="active">Comments</button><button>Details</button><button>Activities</button><button>AI guidance</button></nav>
        <section className="comments-workspace"><section className="incident-main"><div className="comments-head"><div><p className="eyebrow">Incident comments</p><h3>Activity</h3></div><span>Immutable timeline</span></div><Timeline comments={selected.comments} /><CommentComposer incident={selected} teams={teams} activeTeam={activeTeam} onAction={act} requestedAction={preferredAction} onActionChange={setPreferredAction} /></section><Recommendation recommendation={recommendation} minimized={minimized} onToggle={() => setMinimized(!minimized)} /></section>
      </section> : <section className="empty-state"><p className="eyebrow">Incident Desk</p><h2>Select an incident</h2><p>Choose an incident from the queue to view its comments and support guidance.</p></section>}</section>
    </section>
  </main>
}

createRoot(document.getElementById('root')).render(<App />)
