"use client";
import { useEffect, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { briefSchema } from "@/lib/contracts";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Activity,
  ArrowRight,
  Bot,
  Boxes,
  Check,
  Circle,
  Command,
  Download,
  Folder,
  Gauge,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Square,
  Terminal,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { ProjectContext } from "@/components/project-context";
import { Button } from "@/components/ui/button";

type Project = { id: string; name: string; description: string };
type Run = {
  id: string;
  task_id: string;
  status: string;
  status_reason: string | null;
  attempt_count: number;
  budget_microusd: number;
  reserved_microusd: number;
};
type Agent = {
  id: string;
  name: string;
  provider: string;
  model: string | null;
  configuration_status: string;
  implementation_status: string;
  health: string;
  capabilities: string[];
  allowed_tools: string[];
};
type Execution = {
  id: string;
  stage: string;
  agent: string;
  status: string;
  result: { data: Record<string, unknown> } | null;
  reserved_microusd: number;
};
type Approval = {
  id: string;
  run_id: string;
  action_hash: string;
  parameters: Record<string, unknown>;
  decision: string | null;
};
type Artifact = {
  id: string;
  run_id: string;
  name: string;
  sha256: string;
  size: number;
};
type Usage = {
  dispatch_reserved_microusd: number;
  input_tokens: number;
  output_tokens: number;
  provider_reported_cost_usd: number;
  executions: number;
};
type EventRecord = {
  sequence: number;
  kind: string;
  payload: Record<string, unknown>;
};
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchInterval: 4000 } },
});
const views = [
  { id: "overview", name: "Mission control", icon: Command },
  { id: "projects", name: "Projects", icon: Folder },
  { id: "workflow", name: "Workflow studio", icon: GitBranch },
  { id: "agents", name: "Agent control", icon: Bot },
  { id: "approvals", name: "Approvals", icon: ShieldCheck },
  { id: "artifacts", name: "Artifacts", icon: Boxes },
  { id: "usage", name: "Usage", icon: Gauge },
  { id: "settings", name: "Settings", icon: Settings },
];
const schema = briefSchema;
type Brief = z.infer<typeof schema>;
function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <Circle size={7} fill="currentColor" />
      {value.replaceAll("_", " ")}
    </span>
  );
}
function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty">
      <Boxes size={28} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
function Login({ onLogin }: { onLogin: () => void }) {
  const [token, setToken] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <main className="login">
      <div className="login-card">
        <div className="brand">
          <Command />
          <span>
            NEXUS<span className="brand-ai">AI</span>
          </span>
        </div>
        <p className="eyebrow">YOUR AUTONOMOUS WORKSPACE</p>
        <h1>
          Good work starts
          <br />
          with a clear mission.
        </h1>
        <p>
          Connect to your workspace to coordinate agents, inspect execution, and
          approve delivery.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              const r = await fetch("/api/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token }),
              });
              const d = await r.json();
              if (!r.ok) throw Error(d.detail);
              setToken("");
              onLogin();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="token">Workspace access token</label>
          <input
            id="token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          <p className="hint">
            Use the token configured on your NEXUS control plane.
          </p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <Button disabled={busy} type="submit">
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <LockKeyhole size={16} />
            )}
            Connect workspace
            <ArrowRight size={16} />
          </Button>
        </form>
      </div>
    </main>
  );
}
function Console() {
  const qc = useQueryClient(),
    [view, setView] = useState("overview"),
    [projectId, setProjectId] = useState(""),
    [runId, setRunId] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [create, setCreate] = useState(false),
    [name, setName] = useState(""),
    [events, setEvents] = useState<EventRecord[]>([]);
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("projects"),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("runs"),
    enabled: projects.isSuccess,
  });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("agents"),
    enabled: projects.isSuccess,
  });
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<Approval[]>("approvals"),
    enabled: projects.isSuccess,
  });
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => api<Usage>("usage"),
    enabled: projects.isSuccess,
  });
  const executions = useQuery({
    queryKey: ["executions", runId],
    queryFn: () => api<Execution[]>(`runs/${runId}/executions`),
    enabled: !!runId,
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => api<Artifact[]>(`projects/${projectId}/artifacts`),
    enabled: !!projectId,
  });
  const [research, setResearch] = useState(false);
  const [design, setDesign] = useState(false);
  const form = useForm<Brief>({
    resolver: zodResolver(schema),
    defaultValues: { instruction: "", budget: "5.00" },
  });
  const selectedProject = projects.data?.find((p) => p.id === projectId),
    selectedRun = runs.data?.find((r) => r.id === runId);
  useEffect(() => {
    if (!projectId && projects.data?.length) setProjectId(projects.data[0].id);
  }, [projects.data, projectId]);
  useEffect(() => {
    if (!runId && runs.data?.length) setRunId(runs.data[0].id);
  }, [runs.data, runId]);
  useEffect(() => {
    setEvents([]);
    if (!runId) return;
    const source = new EventSource(`/api/control/runs/${runId}/events`);
    source.addEventListener("execution", (e) => {
      const item = JSON.parse((e as MessageEvent).data) as EventRecord;
      setEvents((old) =>
        old.some((x) => x.sequence === item.sequence)
          ? old
          : [...old, item].slice(-200),
      );
    });
    return () => source.close();
  }, [runId]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view]);
  async function action(work: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMessage("");
    try {
      await work();
      await qc.invalidateQueries();
      setMessage(success);
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (projects.error instanceof ApiError && projects.error.status === 401)
    return <Login onLogin={() => qc.invalidateQueries()} />;
  if (projects.isPending)
    return (
      <div className="connecting">
        <LoaderCircle className="spin" />
        Connecting to control plane…
      </div>
    );
  const active =
      runs.data?.filter((r) => ["queued", "running"].includes(r.status))
        .length ?? 0,
    pending = approvals.data?.filter((a) => !a.decision).length ?? 0;
  const currentView = views.find((v) => v.id === view)!;
  const plan = executions.data?.find((e) => e.stage === "planning")?.result
    ?.data;
  const tasks = (plan?.tasks ?? []) as {
    id: string;
    name: string;
    dependencies: string[];
  }[];
  const nodes: Node[] = tasks.map((t, i) => ({
    id: t.id,
    position: { x: 30 + (i % 2) * 270, y: 40 + Math.floor(i / 2) * 120 },
    data: { label: t.name },
    style: {
      background: "#192334",
      color: "#f8fafc",
      border: "1px solid #35505e",
      borderRadius: 10,
      padding: 16,
      width: 220,
    },
  }));
  const edges: Edge[] = tasks.flatMap((t) =>
    t.dependencies.map((d) => ({
      id: `${d}-${t.id}`,
      source: d,
      target: t.id,
      style: { stroke: "#5eead4" },
    })),
  );
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <Command />
          <span>
            NEXUS<span className="brand-ai">AI</span>
          </span>
        </a>
        <div className="workspace-badge">
          <span className="workspace-mark">N</span>
          <div>
            Personal workspace<small>Local control plane</small>
          </div>
          <LockKeyhole size={13} />
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {views.map((v) => (
            <button
              key={v.id}
              className={view === v.id ? "nav-item selected" : "nav-item"}
              onClick={() => setView(v.id)}
              aria-current={view === v.id ? "page" : undefined}
            >
              <v.icon size={18} />
              {v.name}
              {v.id === "approvals" && pending > 0 && (
                <span className="count">{pending}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="system-label">
            <span className="dot" />
            Control plane connected
          </div>
          <p>
            Execution state is persisted.
            <br />
            You stay in control.
          </p>
          <Button
            variant="ghost"
            onClick={async () => {
              await fetch("/api/session", { method: "DELETE" });
              qc.clear();
              window.location.reload();
            }}
          >
            <LogOut size={15} />
            Sign out
          </Button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> {currentView.name}
          </div>
          <div className="topbar-actions">
            <span className="local-label">LOCAL ENVIRONMENT</span>
            <Button
              variant="ghost"
              aria-label="Refresh workspace"
              onClick={() => qc.invalidateQueries()}
            >
              <RefreshCw size={16} />
            </Button>
            <Button
              variant="ghost"
              className="mobile-logout"
              aria-label="Sign out"
              onClick={async () => {
                await fetch("/api/session", { method: "DELETE" });
                qc.clear();
                window.location.reload();
              }}
            >
              <LogOut size={16} />
            </Button>
            <span className="avatar">N</span>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">NEXUS COMMAND CENTER</p>
              <h1>
                {currentView.name}
                <span className="heading-dot">.</span>
              </h1>
              <p>Turn a brief into verified work. Follow every step.</p>
            </div>
            <Button
              onClick={() => {
                setView("projects");
                setCreate(true);
              }}
            >
              <Plus size={16} />
              New project
            </Button>
          </div>
          {(message ||
            projects.error ||
            runs.error ||
            agents.error ||
            approvals.error ||
            artifacts.error ||
            usage.error) && (
            <div className="notice" role="status">
              {message ||
                (projects.error as Error)?.message ||
                (runs.error as Error)?.message ||
                (agents.error as Error)?.message ||
                (approvals.error as Error)?.message ||
                (artifacts.error as Error)?.message ||
                (usage.error as Error)?.message}
              <button
                onClick={() => setMessage("")}
                aria-label="Dismiss message"
              >
                <X size={15} />
              </button>
            </div>
          )}
          {["overview", "projects"].includes(view) && (
            <>
              <section className="metrics" aria-label="Workspace activity">
                <div>
                  <span>
                    <Folder size={16} />
                    Projects
                  </span>
                  <strong>{projects.data?.length ?? 0}</strong>
                  <small>In this workspace</small>
                </div>
                <div>
                  <span>
                    <Activity size={16} />
                    Active workflows
                  </span>
                  <strong>
                    {active}
                    <em className="signal">
                      {active > 0 ? "IN PROGRESS" : "READY"}
                    </em>
                  </strong>
                  <small>Queued or executing</small>
                </div>
                <div>
                  <span>
                    <ShieldCheck size={16} />
                    Awaiting your decision
                  </span>
                  <strong>{pending}</strong>
                  <small>Approval required to deliver</small>
                </div>
                <div>
                  <span>
                    <Gauge size={16} />
                    Dispatch reservations
                  </span>
                  <strong>
                    $
                    {(
                      (usage.data?.dispatch_reserved_microusd ?? 0) / 1e6
                    ).toFixed(2)}
                  </strong>
                  <small>Reserved capacity · not billed cost</small>
                </div>
              </section>
              <div className="overview-grid">
                <section className="panel brief-panel">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">START SOMETHING</span>
                      <h2>What should we build?</h2>
                    </div>
                    <Terminal size={22} />
                  </div>
                  <form
                    onSubmit={form.handleSubmit((data) =>
                      action(async () => {
                        if (!projectId) throw Error("Create a project first");
                        const run = await api<Run>(
                          "tasks",
                          "POST",
                          {
                            project_id: projectId,
                            instruction: data.instruction,
                            budget_microusd: Math.round(
                              Number(data.budget) * 1e6,
                            ),
                          },
                          crypto.randomUUID(),
                        );
                        setRunId(run.id);
                        setView("overview");
                        form.reset({ instruction: "", budget: data.budget });
                      }, "Task queued. The worker will begin when available."),
                    )}
                  >
                    <label htmlFor="project">Project</label>
                    <select
                      id="project"
                      value={projectId}
                      onChange={(e) => setProjectId(e.target.value)}
                    >
                      <option value="">Select a project</option>
                      {projects.data?.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    <label htmlFor="instruction">Project brief</label>
                    <textarea
                      id="instruction"
                      placeholder="Build a French restaurant website with a seasonal menu, accessible navigation, and a refined editorial layout…"
                      {...form.register("instruction")}
                    />
                    {form.formState.errors.instruction && (
                      <p className="error">
                        {form.formState.errors.instruction.message}
                      </p>
                    )}
                    <fieldset className="specialist-options">
                      <legend>Optional specialist stages</legend>
                      <label>
                        <input
                          type="checkbox"
                          checked={research}
                          onChange={(e) => setResearch(e.target.checked)}
                          disabled={
                            !agents.data?.some(
                              (a) =>
                                a.id === "kimi" &&
                                a.configuration_status === "configured",
                            )
                          }
                        />
                        Kimi research synthesis
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={design}
                          onChange={(e) => setDesign(e.target.checked)}
                          disabled={
                            !agents.data?.some(
                              (a) =>
                                a.id === "gemini" &&
                                a.configuration_status === "configured",
                            )
                          }
                        />
                        Gemini design specification
                      </label>
                      <p className="hint">
                        Requires configured providers. Research uses supplied
                        project sources.
                      </p>
                    </fieldset>
                    <div className="brief-footer">
                      <div>
                        <label htmlFor="budget">Dispatch budget (USD)</label>
                        <input
                          id="budget"
                          inputMode="decimal"
                          {...form.register("budget")}
                        />
                      </div>
                      <Button disabled={busy || !projectId} type="submit">
                        <Play size={15} />
                        Start workflow
                      </Button>
                    </div>
                    {form.formState.errors.budget && (
                      <p className="error">
                        {form.formState.errors.budget.message}
                      </p>
                    )}
                    <p className="hint">
                      <ShieldCheck size={12} />
                      Artifacts require your approval before delivery.
                    </p>
                  </form>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Projects</h2>
                    <span className="muted">
                      {projects.data?.length ?? 0} total
                    </span>
                  </div>
                  {create && (
                    <form
                      className="new-project"
                      onSubmit={(e) => {
                        e.preventDefault();
                        action(async () => {
                          const p = await api<Project>("projects", "POST", {
                            name,
                          });
                          setProjectId(p.id);
                          setCreate(false);
                          setName("");
                        }, "Project created");
                      }}
                    >
                      <label htmlFor="project-name">Project name</label>
                      <input
                        id="project-name"
                        autoFocus
                        value={name}
                        maxLength={200}
                        onChange={(e) => setName(e.target.value)}
                        required
                      />
                      <Button type="submit" disabled={busy}>
                        Create project
                      </Button>
                      <Button
                        variant="ghost"
                        type="button"
                        onClick={() => setCreate(false)}
                      >
                        Cancel
                      </Button>
                    </form>
                  )}
                  {!projects.data?.length ? (
                    <Empty
                      title="Your first mission starts here"
                      detail="Create a project, add a brief, and start a workflow."
                    />
                  ) : (
                    <div className="project-list">
                      {projects.data.map((p) => (
                        <button
                          key={p.id}
                          className={
                            p.id === projectId
                              ? "project-row active"
                              : "project-row"
                          }
                          onClick={() => setProjectId(p.id)}
                        >
                          <span className="project-icon">
                            <Folder size={18} />
                          </span>
                          <span>
                            <strong>{p.name}</strong>
                            <small>
                              {p.description || "Ready for your next brief"}
                            </small>
                          </span>
                          <ArrowRight size={16} />
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
          {view === "projects" && selectedProject && (
            <ProjectContext
              key={selectedProject.id}
              project={selectedProject}
              onMessage={setMessage}
            />
          )}
          {["overview", "workflow"].includes(view) && (
            <section className="panel execution-panel">
              <div className="panel-heading">
                <div>
                  <h2>Execution workspace</h2>
                  <p className="muted">
                    Persisted progress, independent review, controlled delivery.
                  </p>
                </div>
                <select
                  aria-label="Select workflow run"
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                >
                  <option value="">Select run</option>
                  {runs.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id.slice(0, 8)} · {r.status}
                    </option>
                  ))}
                </select>
              </div>
              {!selectedRun ? (
                <Empty
                  title="No workflows yet"
                  detail="Submit a project brief to begin. Agent execution is never simulated."
                />
              ) : (
                <>
                  <div className="run-strip">
                    <div>
                      <span className="mono">
                        RUN / {selectedRun.id.slice(0, 8)}
                      </span>
                      <Status value={selectedRun.status} />
                    </div>
                    <div className="run-actions">
                      {selectedRun.status === "blocked" && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            action(
                              () => api(`runs/${runId}/retry`, "POST"),
                              "Run queued for retry",
                            )
                          }
                        >
                          <RefreshCw size={14} />
                          Retry
                        </Button>
                      )}
                      {[
                        "queued",
                        "running",
                        "blocked",
                        "awaiting_approval",
                      ].includes(selectedRun.status) && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            action(
                              () => api(`runs/${runId}/cancel`, "POST"),
                              "Run cancelled",
                            )
                          }
                        >
                          <Square size={12} />
                          Cancel run
                        </Button>
                      )}
                    </div>
                  </div>
                  {selectedRun.status_reason && (
                    <p className="reason">
                      <Terminal size={14} />
                      {selectedRun.status_reason.replaceAll("_", " ")}
                    </p>
                  )}
                  <div className="execution-grid">
                    <div className="timeline">
                      <p className="eyebrow">EXECUTION TIMELINE</p>
                      {!events.length ? (
                        <p className="muted">
                          Waiting for persisted execution events.
                        </p>
                      ) : (
                        events.map((e) => (
                          <div className="timeline-event" key={e.sequence}>
                            <span className="timeline-point" />
                            <div>
                              <strong>{e.kind.replaceAll("_", " ")}</strong>
                              <p>
                                {String(
                                  e.payload.stage ??
                                    e.payload.status ??
                                    e.payload.decision ??
                                    "Workflow update",
                                )}
                              </p>
                            </div>
                            <span className="mono">
                              {String(e.sequence).padStart(2, "0")}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="stage-list">
                      <p className="eyebrow">AGENT OUTPUTS</p>
                      {executions.data?.map((e) => (
                        <details key={e.id}>
                          <summary>
                            <span>
                              <Bot size={15} />
                              {e.stage}
                            </span>
                            <Status value={e.status} />
                          </summary>
                          <pre>
                            {JSON.stringify(
                              e.result?.data ?? { status: e.status },
                              null,
                              2,
                            )}
                          </pre>
                        </details>
                      ))}
                      {!executions.data?.length && (
                        <p className="muted">No agent output recorded.</p>
                      )}
                    </div>
                  </div>
                  {view === "workflow" && (
                    <div className="flow">
                      {nodes.length ? (
                        <ReactFlow
                          nodes={nodes}
                          edges={edges}
                          fitView
                          nodesDraggable={false}
                          nodesConnectable={false}
                          colorMode="dark"
                        >
                          <Background />
                          <Controls />
                        </ReactFlow>
                      ) : (
                        <Empty
                          title="Plan not available yet"
                          detail="A validated planner response will appear here as a dependency graph."
                        />
                      )}
                    </div>
                  )}
                </>
              )}
            </section>
          )}
          {view === "agents" && (
            <section className="agent-grid">
              {agents.data?.map((a) => (
                <article className="panel agent-card" key={a.id}>
                  <div className="agent-icon">
                    <Bot />
                  </div>
                  <div className="agent-title">
                    <h2>{a.name}</h2>
                    <span className="mono">{a.provider}</span>
                  </div>
                  <Status value={a.configuration_status} />
                  <p>{a.capabilities.join(" · ").replaceAll("_", " ")}</p>
                  <dl>
                    <div>
                      <dt>Model</dt>
                      <dd>{a.model ?? "Not selected"}</dd>
                    </div>
                    <div>
                      <dt>Health</dt>
                      <dd>{a.health.replaceAll("_", " ")}</dd>
                    </div>
                    <div>
                      <dt>Adapter</dt>
                      <dd>{a.implementation_status.replaceAll("_", " ")}</dd>
                    </div>
                  </dl>
                  <div className="tool-tags">
                    {a.allowed_tools.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          )}
          {view === "approvals" && (
            <section className="panel">
              <div className="panel-heading">
                <h2>Approval center</h2>
                <ShieldCheck size={20} />
              </div>
              {!approvals.data?.length ? (
                <Empty
                  title="No decisions waiting"
                  detail="Verified artifacts will appear here for approval before delivery."
                />
              ) : (
                approvals.data.map((a) => (
                  <article className="approval" key={a.id}>
                    <div>
                      <h3>Release verified artifacts</h3>
                      <span className="mono">Run {a.run_id.slice(0, 8)}</span>
                      <Status value={a.decision ?? "awaiting_approval"} />
                    </div>
                    <p className="muted">
                      Approve these exact artifact hashes. This action does not
                      deploy or send external messages.
                    </p>
                    <pre>{JSON.stringify(a.parameters, null, 2)}</pre>
                    {!a.decision && (
                      <div className="approval-actions">
                        <Button
                          disabled={busy}
                          onClick={() =>
                            action(
                              () =>
                                api(`approvals/${a.id}/decision`, "POST", {
                                  decision: "approve",
                                  action_hash: a.action_hash,
                                }),
                              "Approved. Workflow queued to resume.",
                            )
                          }
                        >
                          <Check size={16} />
                          Approve delivery
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            action(
                              () =>
                                api(`approvals/${a.id}/decision`, "POST", {
                                  decision: "request_changes",
                                  action_hash: a.action_hash,
                                }),
                              "Changes requested. Delivery rejected.",
                            )
                          }
                        >
                          Request changes
                        </Button>
                        <Button
                          variant="destructive"
                          disabled={busy}
                          onClick={() =>
                            action(
                              () =>
                                api(`approvals/${a.id}/decision`, "POST", {
                                  decision: "reject",
                                  action_hash: a.action_hash,
                                }),
                              "Delivery rejected",
                            )
                          }
                        >
                          Reject
                        </Button>
                      </div>
                    )}
                  </article>
                ))
              )}
            </section>
          )}
          {view === "artifacts" && (
            <section className="panel">
              <div className="panel-heading">
                <h2>Artifact workspace</h2>
                <span className="muted">
                  {selectedProject?.name ??
                    "Select a project in Mission control"}
                </span>
              </div>
              {!artifacts.data?.length ? (
                <Empty
                  title="Deliverables will land here"
                  detail="Only stored, hash-verified files appear. Review downloads are available before delivery approval."
                />
              ) : (
                artifacts.data.map((a) => (
                  <div className="artifact-row" key={a.id}>
                    <Boxes size={22} />
                    <div>
                      <strong>{a.name}</strong>
                      <small className="mono">SHA256 {a.sha256}</small>
                    </div>
                    <span className="muted">
                      {(a.size / 1024).toFixed(1)} KB
                    </span>
                    <a
                      className="button button-outline"
                      href={`/api/control/artifacts/${a.id}`}
                      download
                    >
                      <Download size={15} />
                      Download
                    </a>
                  </div>
                ))
              )}
            </section>
          )}
          {view === "usage" && (
            <section className="panel">
              <div className="panel-heading">
                <h2>Usage analytics</h2>
                <Gauge />
              </div>
              <div className="usage-grid">
                {[
                  ["Input tokens", usage.data?.input_tokens ?? 0],
                  ["Output tokens", usage.data?.output_tokens ?? 0],
                  ["Recorded stages", usage.data?.executions ?? 0],
                  [
                    "Provider-reported cost",
                    `$${(usage.data?.provider_reported_cost_usd ?? 0).toFixed(4)}`,
                  ],
                ].map(([label, value]) => (
                  <div key={label}>
                    <p>{label}</p>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <p className="hint">
                Provider-reported costs are incomplete when a provider does not
                supply cost data. Dispatch reservations are estimates, not
                invoices.
              </p>
            </section>
          )}
          {view === "settings" && (
            <section className="panel settings">
              <h2>Workspace configuration</h2>
              <p>
                Provider credentials and model selections are configured on the
                server. Saved secrets are never returned to this interface.
              </p>
              <h3>Execution policy</h3>
              <dl>
                <div>
                  <dt>Orchestrator</dt>
                  <dd>LangGraph · durable checkpoints</dd>
                </div>
                <div>
                  <dt>Development</dt>
                  <dd>Claude Agent SDK · isolated worktree</dd>
                </div>
                <div>
                  <dt>Review</dt>
                  <dd>Codex SDK · read-only workspace</dd>
                </div>
                <div>
                  <dt>Repair limit</dt>
                  <dd>2 targeted repair iterations</dd>
                </div>
                <div>
                  <dt>Delivery</dt>
                  <dd>Authenticated approval of exact artifact hashes</dd>
                </div>
              </dl>
              <p className="hint">
                Specialist agents and external automation are not yet available.
                Configuration status does not imply a successful health check.
              </p>
            </section>
          )}
          <footer className="content-footer">
            <span>
              <ShieldCheck size={13} /> Application-owned permissions.
              Human-controlled delivery.
            </span>
            <span className="mono">NEXUS / EARLY ACCESS</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
export default function Home() {
  return (
    <QueryClientProvider client={queryClient}>
      <Console />
    </QueryClientProvider>
  );
}
