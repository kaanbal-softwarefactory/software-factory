export const navItems = [
  { id: "overview", label: "Home", kicker: "mission control" },
  { id: "personal", label: "Personal", kicker: "life map" },
  { id: "models", label: "Models", kicker: "ML + DL" },
  { id: "embedded", label: "Embedded", kicker: "one script" },
  { id: "knowledge", label: "Knowledge", kicker: "graph + vectors" },
  { id: "agents", label: "Agents", kicker: "roles + crews" },
  { id: "automations", label: "Automation", kicker: "triggers" },
  { id: "integrations", label: "Integrations", kicker: "MCP + OAuth2" },
  { id: "calendar", label: "Calendar", kicker: "personal OS" },
  { id: "code", label: "Code Studio", kicker: "repo agents" },
  { id: "security", label: "Security", kicker: "rules + audit" },
  { id: "vault", label: "Vault", kicker: "secrets" },
];

export const statusCards = [
  { label: "Runtime", value: "online", detail: "service :4600 + websocket", tone: "ok" },
  { label: "Memory", value: "pgvector", detail: "ready for semantic recall", tone: "info" },
  { label: "Secrets", value: "Vault", detail: "provider keys + OAuth tokens", tone: "ok" },
  { label: "Mode", value: "hybrid", detail: "personal + dev + config", tone: "warn" },
];

export const knowledgeNodes = [
  { id: "profile", label: "User Profile", type: "personal", x: 44, y: 49, size: 74 },
  { id: "team", label: "Team Memory", type: "team", x: 52, y: 24, size: 58 },
  { id: "drive", label: "Drive", type: "source", x: 20, y: 24, size: 48 },
  { id: "confluence", label: "Confluence", type: "source", x: 72, y: 28, size: 48 },
  { id: "s3", label: "S3", type: "source", x: 82, y: 58, size: 44 },
  { id: "repos", label: "Git Repos", type: "source", x: 27, y: 70, size: 50 },
  { id: "calendar", label: "Calendar", type: "source", x: 61, y: 77, size: 44 },
  { id: "logs", label: "Logs", type: "system", x: 13, y: 51, size: 42 },
  { id: "apps", label: "Kaanbal Apps", type: "system", x: 72, y: 48, size: 55 },
];

export const contextRows = [
  { label: "Personal", detail: "profile, routines, private notes, health, study, goals", visibility: "private" },
  { label: "Team", detail: "shared decisions, project memory, app context, public summaries", visibility: "shared" },
  { label: "System", detail: "pods, logs, deployments, workers, infra config, incidents", visibility: "admin" },
  { label: "Verified", detail: "citations, DOI checks, official docs, source snapshots", visibility: "audited" },
];

export const agents = [
  { role: "Orchestrator", scope: "routes work, merges context, requests approvals", state: "active" },
  { role: "Security", scope: "permissions, secrets, threat review, command policy", state: "ready" },
  { role: "QA Tester", scope: "acceptance criteria, regression maps, evidence", state: "ready" },
  { role: "Frontend", scope: "UI systems, accessibility, embedded widgets", state: "ready" },
  { role: "Backend", scope: "APIs, data contracts, workers, queues", state: "ready" },
  { role: "DevOps", scope: "Kaanbal, clusters, GitOps, runtime health", state: "ready" },
  { role: "Data / ML", scope: "feature stores, evals, vector memory, MLOps", state: "planned" },
  { role: "Scientific", scope: "DOI validation, claims, experiment logs", state: "ready" },
];

export const workflows = [
  { name: "Register improvement", trigger: "user idea", output: "board card + role plan", risk: "low" },
  { name: "Scientific validation", trigger: "claim or paper", output: "evidence pack + DOI check", risk: "medium" },
  { name: "Incident diagnosis", trigger: "log anomaly", output: "root cause path + commands", risk: "high" },
  { name: "Deploy assistant", trigger: "release event", output: "dev -> staging -> prod checklist", risk: "high" },
  { name: "Personal planning", trigger: "calendar + goals", output: "agenda, reminders, pomodoro", risk: "low" },
  { name: "Code agent", trigger: "repo request", output: "branch plan + patch proposal", risk: "high" },
];

export const integrations = [
  { name: "n8n internal", kind: "workflow engine", auth: "service token", status: "recommended" },
  { name: "MCP standard", kind: "tool protocol", auth: "per server policy", status: "core" },
  { name: "Local MCP", kind: "filesystem/system", auth: "device trust", status: "planned" },
  { name: "Atlassian", kind: "Jira + Confluence", auth: "OAuth2", status: "connector" },
  { name: "Google Drive", kind: "docs + sheets + files", auth: "OAuth2", status: "connector" },
  { name: "Miro", kind: "visual boards", auth: "OAuth2", status: "connector" },
  { name: "S3", kind: "object storage", auth: "Vault secret", status: "connector" },
  { name: "Webhooks", kind: "HTTP events", auth: "signed URL", status: "core" },
];

export const automationTriggers = [
  { name: "Webhook", detail: "POST events from apps, n8n, CI, IoT, forms" },
  { name: "Schedule", detail: "periodic prompts, health checks, agenda scans" },
  { name: "UI event", detail: "embedded context: page, button, route, form" },
  { name: "Log pattern", detail: "watch errors, restarts, failed jobs" },
  { name: "Calendar", detail: "meetings, prep reminders, focus blocks" },
  { name: "Manual approval", detail: "human gate for commands and deploys" },
];

export const automationScripts = [
  {
    name: "Log anomaly triage",
    language: "Python",
    source: "logs.query(errors=True, last='15m')",
    output: "incident summary + suggested owner",
    policy: "assisted",
  },
  {
    name: "Daily personal digest",
    language: "Python",
    source: "calendar + tasks + voice notes",
    output: "agenda, reminders, focus windows",
    policy: "private",
  },
  {
    name: "Kaanbal deploy check",
    language: "Bash",
    source: "kubectl get pods && health endpoints",
    output: "ready / blocked report",
    policy: "approval",
  },
  {
    name: "n8n workflow call",
    language: "HTTP",
    source: "POST internal n8n webhook",
    output: "workflow result + audit id",
    policy: "signed",
  },
];

export const boardColumns = [
  {
    id: "ideas",
    title: "Ideas",
    cards: [
      "Mobile companion with voice notes and day capture",
      "Vector memory with personal and team boundaries",
      "MCP catalog with OAuth2 connector setup",
    ],
  },
  {
    id: "analysis",
    title: "Analysis",
    cards: [
      "Choose Postgres + pgvector for POC, Qdrant option for scale",
      "Map root/system executor policies and approval states",
    ],
  },
  {
    id: "dev",
    title: "Dev",
    cards: [
      "Embed widget medium/full shell",
      "Agent Command Center Vue shell",
    ],
  },
  {
    id: "staging",
    title: "Staging",
    cards: ["Kaanbal installer starts runtime and links central UI"],
  },
  {
    id: "done",
    title: "Done",
    cards: ["Independent Acuaponsito runtime concept"],
  },
];

export const userSession = {
  name: "Andre",
  role: "Admin Builder",
  workspace: "Software Factory",
  session: "kbl-fable-2026",
  presence: "active",
};

export const sessionNotifications = [
  { title: "Model routing", detail: "3 provider keys pending Vault validation", tone: "warn" },
  { title: "Personal memory", detail: "Daily digest can be generated at 21:00", tone: "ok" },
  { title: "Automation lab", detail: "Script dry-run requires approval policy", tone: "info" },
];

export const assistantModes = [
  { id: "personal", label: "Personal", detail: "calm space for routines, interests, commitments and wellbeing" },
  { id: "dev", label: "Dev", detail: "technical cockpit for systems, code, automations and deployments" },
  { id: "config", label: "Config", detail: "providers, themes, privacy, roles, permissions and secrets" },
];

export const themePresets = [
  { id: "nebula", label: "Dev Nebula", detail: "dark technical, high contrast, system telemetry" },
  { id: "calm", label: "Calm Personal", detail: "softer contrast, warmer panels, confidence and focus" },
  { id: "bio", label: "Bio Lab", detail: "science, biotechnology, research and clean evidence" },
  { id: "sunrise", label: "Soft Sunrise", detail: "personal planning, health, school and routines" },
];

export const agentMediaModes = [
  { id: "video", label: "Video", detail: "use clip catalog and smooth crossfade between states" },
  { id: "voice", label: "Voice", detail: "voice-first assistant with transcript and confirmations" },
  { id: "svg", label: "SVG light", detail: "animated lightweight face that imitates clips when video is heavy" },
  { id: "hybrid", label: "Hybrid", detail: "video when expressive, SVG when performance matters, voice optional" },
];

export const personalGraphNodes = [
  { id: "self", label: "Me", type: "personal", x: 50, y: 48, size: 68 },
  { id: "health", label: "Health", type: "calm", x: 22, y: 25, size: 46 },
  { id: "school", label: "School", type: "calm", x: 20, y: 68, size: 44 },
  { id: "family", label: "Family", type: "warm", x: 45, y: 20, size: 48 },
  { id: "work", label: "Work", type: "system", x: 76, y: 35, size: 50 },
  { id: "science", label: "Science", type: "source", x: 72, y: 72, size: 46 },
  { id: "projects", label: "Projects", type: "team", x: 50, y: 80, size: 52 },
];

export const personalFocus = [
  { area: "Health", signal: "sleep, food, movement, lab notes", next: "ask for daily check-in" },
  { area: "Study", signal: "AI, biotech, science notes", next: "build spaced review cards" },
  { area: "Family", signal: "shared plans and private memories", next: "keep personal by default" },
  { area: "Work", signal: "Kaanbal, repos, deployments", next: "separate dev context from private life" },
  { area: "IoT", signal: "camera, microphone, sensors", next: "capture only with explicit device policy" },
];

export const personalTasks = [
  { title: "Organize tomorrow from calendar", kind: "personal", priority: "high" },
  { title: "Review phagotherapy ML ideas", kind: "research", priority: "high" },
  { title: "Create agent mobile companion concept", kind: "product", priority: "medium" },
  { title: "Log health and focus routine", kind: "wellbeing", priority: "medium" },
];

export const modelCatalog = [
  {
    name: "LLM frontier router",
    family: "Language / agent",
    provider: "OpenAI, Anthropic, DeepSeek, local",
    use: "chat, planning, code, research, tool selection",
    governance: "provider key in Vault; no browser token persistence",
  },
  {
    name: "Bio sequence classifier",
    family: "Deep learning",
    provider: "custom PyTorch",
    use: "phagotherapy-style sequence screening and feature ranking",
    governance: "research workspace; evidence pack required",
  },
  {
    name: "Graph recommender",
    family: "Machine learning",
    provider: "scikit-learn / graph features",
    use: "interests, commitments, next-best-action suggestions",
    governance: "private profile by default",
  },
  {
    name: "Anomaly detector",
    family: "Machine learning",
    provider: "local service",
    use: "logs, pods, workers, deploy health and incident signals",
    governance: "admin-only system context",
  },
  {
    name: "Vision day capture",
    family: "Computer vision",
    provider: "local or edge model",
    use: "IoT camera snapshots, habit tracking, lab/device observations",
    governance: "explicit consent, device policy, retention limits",
  },
  {
    name: "Speech memory encoder",
    family: "Audio / embeddings",
    provider: "local or cloud",
    use: "voice notes, meetings, reminders and personal summaries",
    governance: "private audio vault + redaction",
  },
];

export const mlPipelines = [
  { step: "Ingest", detail: "documents, repos, logs, sensors, calendars, DOI papers and user notes" },
  { step: "Normalize", detail: "metadata, permissions, source identity, evidence and retention policy" },
  { step: "Embed", detail: "vectors, graph edges, summaries and searchable memory chunks" },
  { step: "Train / route", detail: "choose ML model, deep model, LLM provider or n8n workflow" },
  { step: "Evaluate", detail: "scientific validation, tests, bias checks, hallucination checks and audit" },
  { step: "Deploy", detail: "dev, staging, production or personal device with rollback and monitoring" },
];

export const systemDiagramSteps = [
  { label: "Private user sources", detail: "OAuth2 Drive, calendar, notes, voice, photos, IoT" },
  { label: "Shared workspace", detail: "Kaanbal apps, group context, allowed projects, MCP tools" },
  { label: "Agent runtime", detail: "router, memory, skills, policies, model registry, WebSocket" },
  { label: "Knowledge layer", detail: "Postgres, pgvector, graph edges, source snapshots, evidence" },
  { label: "Governance", detail: "roles, approvals, Vault, audit logs, command classes" },
  { label: "Action layer", detail: "n8n, MCP, APIs, local executor, scripts, notifications" },
];

export const calendarItems = [
  { time: "08:30", title: "Morning health + focus scan", type: "personal" },
  { time: "10:00", title: "Project standup prep from memory", type: "team" },
  { time: "13:00", title: "Study block: AI systems", type: "school" },
  { time: "16:30", title: "Kaanbal deploy review", type: "work" },
  { time: "21:00", title: "Daily summary + tomorrow plan", type: "personal" },
];

export const codeWorkspaces = [
  { repo: "software-factory", branch: "agent-command-center", model: "gpt / claude / local", status: "designing" },
  { repo: "acuaponsito-runtime", branch: "embed-shell", model: "fast small model", status: "ready" },
  { repo: "kaanbal-api", branch: "agent-api", model: "code specialist", status: "planned" },
];

export const securityPolicies = [
  { label: "Read only", detail: "inspect context, never mutate", level: 1 },
  { label: "Assisted", detail: "propose actions, wait for user", level: 2 },
  { label: "Dev executor", detail: "apply changes only in dev sandbox", level: 3 },
  { label: "Staging gate", detail: "approval + audit log required", level: 4 },
  { label: "Root access", detail: "explicit session, command allowlist, Vault identity", level: 5 },
];

export const vaultItems = [
  { name: "LLM providers", secret: "deepseek / openai / anthropic", owner: "agent runtime" },
  { name: "OAuth2 connectors", secret: "drive / atlassian / miro", owner: "user identity" },
  { name: "n8n internal", secret: "workflow tokens", owner: "automation" },
  { name: "System executor", secret: "sudo policy / host token", owner: "admin" },
];
