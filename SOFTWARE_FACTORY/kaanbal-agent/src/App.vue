<script setup>
import { computed, ref } from "vue";
import {
  agentMediaModes,
  agents,
  assistantModes,
  automationScripts,
  automationTriggers,
  boardColumns,
  calendarItems,
  codeWorkspaces,
  contextRows,
  integrations,
  knowledgeNodes,
  mlPipelines,
  modelCatalog,
  navItems,
  personalFocus,
  personalGraphNodes,
  personalTasks,
  securityPolicies,
  sessionNotifications,
  statusCards,
  systemDiagramSteps,
  themePresets,
  userSession,
  vaultItems,
  workflows,
} from "./data/commandCenter";

const activeSection = ref("overview");
const panelMode = ref("small");
const contextMode = ref("personal");
const shellMode = ref("dev");
const themePreset = ref("nebula");
const autonomyMode = ref("Assisted");
const agentMediaMode = ref("hybrid");
const assistantOpen = ref(false);
const isDraggingAgent = ref(false);
const agentPosition = ref({ x: 28, y: 28 });
const selectedConnector = ref(integrations[0]);
const selectedAgent = ref(agents[0]);
const selectedAutomation = ref(automationScripts[0]);

const activeNav = computed(() => navItems.find((item) => item.id === activeSection.value));
const primaryKnowledgeNodes = computed(() => knowledgeNodes.filter((node) => node.type !== "system"));
const systemKnowledgeNodes = computed(() => knowledgeNodes.filter((node) => node.type === "system"));
const selectedTheme = computed(() => themePresets.find((theme) => theme.id === themePreset.value));
const selectedMode = computed(() => assistantModes.find((mode) => mode.id === shellMode.value));
const selectedMedia = computed(() => agentMediaModes.find((mode) => mode.id === agentMediaMode.value));
const activeAutomationPreview = computed(() => {
  if (!selectedAutomation.value) return "";

  return `# ${selectedAutomation.value.name}
policy = "${selectedAutomation.value.policy}"
source = "${selectedAutomation.value.source}"

def run(context):
    result = agent.tools.execute(source, dry_run=True)
    return {
        "status": "ready_for_review",
        "output": "${selectedAutomation.value.output}",
        "audit": "preview-only"
    }`;
});

function setSection(id) {
  activeSection.value = id;
}

function selectConnector(connector) {
  selectedConnector.value = connector;
}

function selectAgent(agent) {
  selectedAgent.value = agent;
}

function selectAutomation(script) {
  selectedAutomation.value = script;
}

function cycleAgentMedia() {
  const index = agentMediaModes.findIndex((mode) => mode.id === agentMediaMode.value);
  agentMediaMode.value = agentMediaModes[(index + 1) % agentMediaModes.length].id;
}

function startAgentDrag(event) {
  if (event.target.closest("button")) return;
  isDraggingAgent.value = true;
  const startX = event.clientX;
  const startY = event.clientY;
  const startPosition = { ...agentPosition.value };

  function moveAgent(moveEvent) {
    if (!isDraggingAgent.value) return;
    agentPosition.value = {
      x: Math.max(12, startPosition.x - (moveEvent.clientX - startX)),
      y: Math.max(12, startPosition.y - (moveEvent.clientY - startY)),
    };
  }

  function stopAgentDrag() {
    isDraggingAgent.value = false;
    window.removeEventListener("pointermove", moveAgent);
    window.removeEventListener("pointerup", stopAgentDrag);
  }

  window.addEventListener("pointermove", moveAgent);
  window.addEventListener("pointerup", stopAgentDrag);
}
</script>

<template>
  <div class="app-shell" :class="[`mode-${shellMode}`, `theme-${themePreset}`]">
    <aside class="side-rail" aria-label="Command Center navigation">
      <div class="brand-block">
        <div class="brand-glyph" aria-hidden="true">
          <span></span>
        </div>
        <div>
          <strong>Acuaponsito</strong>
          <small>Command Center</small>
        </div>
      </div>

      <nav class="nav-list">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="nav-item"
          :class="{ active: activeSection === item.id }"
          type="button"
          @click="setSection(item.id)"
        >
          <span>{{ item.label }}</span>
          <small>{{ item.kicker }}</small>
        </button>
      </nav>

      <div class="rail-footer">
        <span>Runtime :4600</span>
        <strong>Admin POC</strong>
      </div>
    </aside>

    <main class="command-main">
      <header class="topbar">
        <div>
          <span class="eyebrow">{{ activeNav?.kicker }}</span>
          <h1>Acuaponsito Command Center</h1>
          <p class="topbar-subtitle">
            {{ selectedMode?.detail }}
          </p>
        </div>
        <div class="top-actions">
          <div class="session-card">
            <span>{{ userSession.workspace }}</span>
            <strong>{{ userSession.name }} · {{ userSession.role }}</strong>
            <small>session {{ userSession.session }}</small>
          </div>
          <div class="mode-switch" aria-label="Assistant mode">
            <button
              v-for="mode in assistantModes"
              :key="mode.id"
              type="button"
              :class="{ active: shellMode === mode.id }"
              @click="shellMode = mode.id"
            >
              {{ mode.label }}
            </button>
          </div>
        </div>
      </header>

      <section class="control-strip" aria-label="Session controls">
        <div class="theme-selector">
          <span>Theme</span>
          <button
            v-for="theme in themePresets"
            :key="theme.id"
            type="button"
            :class="{ active: themePreset === theme.id }"
            @click="themePreset = theme.id"
          >
            {{ theme.label }}
          </button>
          <button class="context-toggle" type="button" @click="contextMode = contextMode === 'personal' ? 'team' : 'personal'">
            {{ contextMode === "personal" ? "Private context" : "Team context" }}
          </button>
        </div>
        <div class="notification-strip">
          <article v-for="notification in sessionNotifications" :key="notification.title" :class="notification.tone">
            <strong>{{ notification.title }}</strong>
            <span>{{ notification.detail }}</span>
          </article>
        </div>
      </section>

      <section class="status-grid" aria-label="Runtime status">
        <article v-for="card in statusCards" :key="card.label" class="status-card" :class="card.tone">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.detail }}</small>
        </article>
      </section>

      <section v-if="activeSection === 'overview'" class="layout overview-layout">
        <div class="hero-panel panel">
          <div class="hero-copy">
            <span class="eyebrow">bio / space / software factory</span>
            <h2>One assistant service for work, research, code, routines, teams and systems.</h2>
            <p>
              The runtime owns API, WebSocket, memory, approvals, integrations and the embeddable widget.
              Kaanbal starts it, Vault protects it, and every app can host it with one script.
            </p>
            <div class="hero-actions">
              <button class="primary-action" type="button" @click="setSection('embedded')">Design embedded shell</button>
              <button class="secondary-action" type="button" @click="setSection('knowledge')">Map knowledge</button>
            </div>
          </div>
          <div class="bot-orbit">
            <div class="bot-card">
              <div class="bot-face">
                <span></span>
                <span></span>
              </div>
              <div class="bot-core"></div>
            </div>
            <div class="orbit-label top">Vector memory</div>
            <div class="orbit-label right">MCP tools</div>
            <div class="orbit-label bottom">Vault policy</div>
          </div>
        </div>

        <div class="panel command-stack">
          <div class="panel-head">
            <div>
              <span class="eyebrow">next build layers</span>
              <h3>Architecture decisions</h3>
            </div>
            <span class="soft-badge">POC shell</span>
          </div>
          <div class="decision-list">
            <div>
              <strong>Runtime service</strong>
              <span>Independent container/process with UI, API, WebSocket and embed.js.</span>
            </div>
            <div>
              <strong>Storage</strong>
              <span>Postgres for users/config, pgvector for semantic memory, Vault for secrets.</span>
            </div>
            <div>
              <strong>Automations</strong>
              <span>Native triggers plus n8n internal workflows exposed as agent tools.</span>
            </div>
            <div>
              <strong>Safety</strong>
              <span>Root/system executor only through explicit approval, policies and audit trails.</span>
            </div>
          </div>
        </div>

        <div class="panel board-panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">self improvement</span>
              <h3>Ideas to implementation board</h3>
            </div>
            <button class="text-button" type="button">Register improvement</button>
          </div>
          <div class="board-grid">
            <article v-for="column in boardColumns" :key="column.id" class="board-column">
              <h4>{{ column.title }}</h4>
              <div v-for="card in column.cards" :key="card" class="board-card">{{ card }}</div>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'personal'" class="layout personal-layout">
        <div class="panel personal-home">
          <div class="panel-head">
            <div>
              <span class="eyebrow">personal mode</span>
              <h3>Life map, commitments and calm planning</h3>
            </div>
            <span class="soft-badge">{{ selectedTheme?.label }}</span>
          </div>
          <div class="personal-grid">
            <div class="photo-collage" aria-label="Personal collage placeholder">
              <div class="photo-tile main">family</div>
              <div class="photo-tile">health</div>
              <div class="photo-tile">study</div>
              <div class="photo-tile">lab</div>
              <div class="photo-tile">space</div>
            </div>
            <div class="personal-summary">
              <strong>A quieter assistant surface</strong>
              <p>
                Personal mode keeps private routines, health, school, interests, family and projects separated
                from shared Kaanbal system memory unless you explicitly promote something to team context.
              </p>
              <div class="personal-kpis">
                <span>4 focus blocks</span>
                <span>2 commitments due</span>
                <span>1 health check-in</span>
              </div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">today</span>
              <h3>Personal task lens</h3>
            </div>
          </div>
          <article v-for="task in personalTasks" :key="task.title" class="personal-task">
            <strong>{{ task.title }}</strong>
            <span>{{ task.kind }}</span>
            <small>{{ task.priority }}</small>
          </article>
        </div>

        <div class="panel graph-panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">identity graph</span>
              <h3>Projects, interests, commitments and private memory</h3>
            </div>
            <span class="soft-badge">private first</span>
          </div>
          <div class="graph-canvas personal-graph">
            <svg viewBox="0 0 900 520" role="img" aria-label="Personal graph mockup">
              <line
                v-for="node in personalGraphNodes.filter((node) => node.id !== 'self')"
                :key="`p-${node.id}`"
                :x1="`${personalGraphNodes[0].x}%`"
                :y1="`${personalGraphNodes[0].y}%`"
                :x2="`${node.x}%`"
                :y2="`${node.y}%`"
              />
              <g v-for="node in personalGraphNodes" :key="node.id">
                <circle :cx="`${node.x}%`" :cy="`${node.y}%`" :r="node.size / 2" :class="node.type" />
                <text :x="`${node.x}%`" :y="`${node.y}%`">{{ node.label }}</text>
              </g>
            </svg>
          </div>
        </div>

        <div class="panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">capture sources</span>
              <h3>Interests, health, IoT and personal routines</h3>
            </div>
          </div>
          <div class="personal-focus-grid">
            <article v-for="item in personalFocus" :key="item.area">
              <strong>{{ item.area }}</strong>
              <span>{{ item.signal }}</span>
              <small>{{ item.next }}</small>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'models'" class="layout models-layout">
        <div class="panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">model registry</span>
              <h3>LLM, machine learning and deep learning catalog</h3>
            </div>
            <span class="soft-badge">admin curated</span>
          </div>
          <div class="model-grid">
            <article v-for="model in modelCatalog" :key="model.name" class="model-card">
              <div>
                <strong>{{ model.name }}</strong>
                <small>{{ model.family }}</small>
              </div>
              <span>{{ model.provider }}</span>
              <p>{{ model.use }}</p>
              <em>{{ model.governance }}</em>
            </article>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">ML ops</span>
              <h3>Pipeline from data to action</h3>
            </div>
          </div>
          <div class="pipeline-list">
            <article v-for="step in mlPipelines" :key="step.step">
              <strong>{{ step.step }}</strong>
              <span>{{ step.detail }}</span>
            </article>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">architecture</span>
              <h3>Knowledge, governance and action flow</h3>
            </div>
          </div>
          <div class="system-diagram">
            <article v-for="step in systemDiagramSteps" :key="step.label">
              <strong>{{ step.label }}</strong>
              <span>{{ step.detail }}</span>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'embedded'" class="layout embedded-layout">
        <div class="panel embed-preview">
          <div class="panel-head">
            <div>
              <span class="eyebrow">host preview</span>
              <h3>Embedded assistant shell</h3>
            </div>
            <div class="segmented-control" aria-label="Widget size">
              <button
                v-for="mode in ['small', 'medium', 'full']"
                :key="mode"
                type="button"
                :class="{ active: panelMode === mode }"
                @click="panelMode = mode"
              >
                {{ mode }}
              </button>
            </div>
          </div>
          <div class="host-window">
            <div class="host-bar">
              <span></span>
              <span></span>
              <span></span>
              <strong>Any host app</strong>
            </div>
            <div class="host-content">
              <div class="fake-table">
                <div v-for="n in 9" :key="n"></div>
              </div>
              <div class="floating-bot" :class="panelMode">
                <div class="mini-bot"></div>
                <button type="button" @click="panelMode = panelMode === 'full' ? 'small' : 'medium'">
                  {{ panelMode === "small" ? "open" : "central UI" }}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">embedded layer</span>
              <h3>Widget states</h3>
            </div>
          </div>
          <div class="spec-list">
            <div><strong>Small</strong><span>Draggable video button. Hover grows 2x. No host DOM collision.</span></div>
            <div><strong>Medium</strong><span>Panel opens over the page; floating button disappears.</span></div>
            <div><strong>Full</strong><span>Command Center overlay with central link and session continuity.</span></div>
            <div><strong>Central link</strong><span>Every embed links back to the main assistant service UI.</span></div>
          </div>
          <div class="media-mode-list">
            <h4>Agent media modes</h4>
            <article v-for="mode in agentMediaModes" :key="mode.id">
              <strong>{{ mode.label }}</strong>
              <span>{{ mode.detail }}</span>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'knowledge'" class="layout knowledge-layout">
        <div class="panel graph-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">knowledge graph</span>
              <h3>Personal, team and system memory</h3>
            </div>
            <span class="soft-badge">pgvector POC</span>
          </div>
          <div class="graph-canvas">
            <svg viewBox="0 0 900 520" role="img" aria-label="Knowledge graph mockup">
              <line
                v-for="node in primaryKnowledgeNodes"
                :key="`a-${node.id}`"
                :x1="`${knowledgeNodes[0].x}%`"
                :y1="`${knowledgeNodes[0].y}%`"
                :x2="`${node.x}%`"
                :y2="`${node.y}%`"
              />
              <line
                v-for="node in systemKnowledgeNodes"
                :key="`b-${node.id}`"
                x1="52%"
                y1="48%"
                :x2="`${node.x}%`"
                :y2="`${node.y}%`"
              />
              <g v-for="node in knowledgeNodes" :key="node.id">
                <circle :cx="`${node.x}%`" :cy="`${node.y}%`" :r="node.size / 2" :class="node.type" />
                <text :x="`${node.x}%`" :y="`${node.y}%`">{{ node.label }}</text>
              </g>
            </svg>
          </div>
        </div>
        <div class="panel context-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">context boundaries</span>
              <h3>Recall policy</h3>
            </div>
          </div>
          <article v-for="row in contextRows" :key="row.label" class="context-row">
            <strong>{{ row.label }}</strong>
            <span>{{ row.detail }}</span>
            <small>{{ row.visibility }}</small>
          </article>
        </div>
      </section>

      <section v-else-if="activeSection === 'agents'" class="layout agents-layout">
        <div class="panel agent-list">
          <div class="panel-head">
            <div>
              <span class="eyebrow">agent crews</span>
              <h3>Roles and subagents</h3>
            </div>
            <button class="text-button" type="button">New role</button>
          </div>
          <button
            v-for="agent in agents"
            :key="agent.role"
            type="button"
            class="agent-row"
            :class="{ active: selectedAgent.role === agent.role }"
            @click="selectAgent(agent)"
          >
            <strong>{{ agent.role }}</strong>
            <span>{{ agent.scope }}</span>
            <small>{{ agent.state }}</small>
          </button>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">selected role</span>
              <h3>{{ selectedAgent.role }}</h3>
            </div>
            <span class="soft-badge">{{ selectedAgent.state }}</span>
          </div>
          <div class="role-detail">
            <p>{{ selectedAgent.scope }}</p>
            <div class="cap-grid">
              <span>Prompt profile</span>
              <span>Tool policy</span>
              <span>Memory scope</span>
              <span>Approval tier</span>
              <span>Model route</span>
              <span>Workspace access</span>
            </div>
          </div>
          <div class="workflow-stack">
            <h4>Workflow templates</h4>
            <article v-for="flow in workflows" :key="flow.name">
              <strong>{{ flow.name }}</strong>
              <span>{{ flow.trigger }} -> {{ flow.output }}</span>
              <small>{{ flow.risk }} risk</small>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'automations'" class="layout automation-layout">
        <div class="panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">triggers</span>
              <h3>Automation and workflow fabric</h3>
            </div>
            <span class="soft-badge">native + n8n</span>
          </div>
          <div class="trigger-grid">
            <article v-for="trigger in automationTriggers" :key="trigger.name">
              <strong>{{ trigger.name }}</strong>
              <span>{{ trigger.detail }}</span>
            </article>
          </div>
        </div>
        <div class="panel wide automation-builder">
          <div class="panel-head">
            <div>
              <span class="eyebrow">automation lab</span>
              <h3>AI-assisted script, rule and plugin builder</h3>
            </div>
            <span class="soft-badge">dry-run first</span>
          </div>
          <div class="builder-layout">
            <div class="script-list">
              <button
                v-for="script in automationScripts"
                :key="script.name"
                type="button"
                :class="{ active: selectedAutomation.name === script.name }"
                @click="selectAutomation(script)"
              >
                <strong>{{ script.name }}</strong>
                <span>{{ script.language }} · {{ script.policy }}</span>
              </button>
            </div>
            <div class="script-preview">
              <div class="code-tabs">
                <span>{{ selectedAutomation.language }}</span>
                <span>preview only</span>
                <span>{{ selectedAutomation.policy }}</span>
              </div>
              <pre><code>{{ activeAutomationPreview }}</code></pre>
            </div>
            <div class="test-output">
              <strong>Simulated output</strong>
              <span>{{ selectedAutomation.output }}</span>
              <small>Next phase: run in sandbox, capture stdout, store audit, then deploy to native trigger or n8n.</small>
            </div>
          </div>
        </div>
        <div class="panel wide board-panel">
          <div class="timeline-grid">
            <div class="timeline-line"></div>
            <article>
              <strong>Event enters</strong>
              <span>Webhook, schedule, UI event, log pattern or calendar signal.</span>
            </article>
            <article>
              <strong>Agent classifies</strong>
              <span>Personal, team, system, scientific or code workflow.</span>
            </article>
            <article>
              <strong>Tools execute</strong>
              <span>n8n/MCP/local executor run only inside policy.</span>
            </article>
            <article>
              <strong>Memory updates</strong>
              <span>Summary, evidence and searchable vector chunks are saved.</span>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'integrations'" class="layout integrations-layout">
        <div class="panel connectors-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">connectors</span>
              <h3>MCP, n8n, OAuth2 and endpoints</h3>
            </div>
            <button class="text-button" type="button">Add connector</button>
          </div>
          <button
            v-for="integration in integrations"
            :key="integration.name"
            class="connector-row"
            :class="{ active: selectedConnector.name === integration.name }"
            type="button"
            @click="selectConnector(integration)"
          >
            <strong>{{ integration.name }}</strong>
            <span>{{ integration.kind }}</span>
            <small>{{ integration.status }}</small>
          </button>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">connector setup</span>
              <h3>{{ selectedConnector.name }}</h3>
            </div>
            <span class="soft-badge">{{ selectedConnector.auth }}</span>
          </div>
          <div class="connector-detail">
            <label>Auth method<input :value="selectedConnector.auth" readonly /></label>
            <label>Internal URL<input value="https://service.internal/api" readonly /></label>
            <label>Vault path<input value="secret/acua/connectors/provider" readonly /></label>
            <label>Allowed scopes<input value="read, summarize, create-task, notify" readonly /></label>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'calendar'" class="layout calendar-layout">
        <div class="panel day-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">personal operating system</span>
              <h3>Agenda, routines and reminders</h3>
            </div>
            <span class="soft-badge">mobile companion ready</span>
          </div>
          <article v-for="item in calendarItems" :key="item.time" class="calendar-row">
            <strong>{{ item.time }}</strong>
            <span>{{ item.title }}</span>
            <small>{{ item.type }}</small>
          </article>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">daily capture</span>
              <h3>Mobile companion</h3>
            </div>
          </div>
          <div class="mobile-card">
            <div class="phone-frame">
              <div class="phone-status"></div>
              <div class="phone-line wide"></div>
              <div class="phone-line"></div>
              <div class="phone-grid"></div>
              <button type="button">Record day note</button>
            </div>
            <p>React Native app for voice notes, reminders, calendar conflict checks, routines, health, study and focus blocks.</p>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'code'" class="layout code-layout">
        <div class="panel code-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">cursor online</span>
              <h3>Repo-aware code studio</h3>
            </div>
            <span class="soft-badge">proposal mode</span>
          </div>
          <div class="code-window">
            <div class="code-tabs">
              <span>agent.plan.md</span>
              <span>App.vue</span>
              <span>policy.yaml</span>
            </div>
            <pre><code>agent:
  mode: dev
  requires_approval: true
  models:
    - frontier
    - local-code
  tools:
    - repo.read
    - patch.propose
    - tests.run</code></pre>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">workspaces</span>
              <h3>Live repositories</h3>
            </div>
          </div>
          <article v-for="workspace in codeWorkspaces" :key="workspace.repo" class="workspace-row">
            <strong>{{ workspace.repo }}</strong>
            <span>{{ workspace.branch }}</span>
            <small>{{ workspace.model }} / {{ workspace.status }}</small>
          </article>
        </div>
      </section>

      <section v-else-if="activeSection === 'security'" class="layout security-layout">
        <div class="panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">safety model</span>
              <h3>Role rules, command classes and approvals</h3>
            </div>
            <span class="soft-badge">{{ autonomyMode }}</span>
          </div>
          <div class="policy-grid">
            <button
              v-for="policy in securityPolicies"
              :key="policy.label"
              class="policy-card"
              :class="{ active: autonomyMode === policy.label }"
              type="button"
              @click="autonomyMode = policy.label"
            >
              <strong>{{ policy.label }}</strong>
              <span>{{ policy.detail }}</span>
              <small>tier {{ policy.level }}</small>
            </button>
          </div>
        </div>
        <div class="panel wide">
          <div class="approval-lane">
            <article>
              <strong>1. Agent proposes</strong>
              <span>Command, reason, affected scope and rollback hint.</span>
            </article>
            <article>
              <strong>2. Policy checks</strong>
              <span>Allowlist, environment, user role and risk tier.</span>
            </article>
            <article>
              <strong>3. Human approves</strong>
              <span>Admin gate for root, staging, production and secrets.</span>
            </article>
            <article>
              <strong>4. Audit writes</strong>
              <span>Output, identity, timestamp and evidence are saved.</span>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'vault'" class="layout vault-layout">
        <div class="panel wide">
          <div class="panel-head">
            <div>
              <span class="eyebrow">hashicorp vault</span>
              <h3>Secrets and identity fabric</h3>
            </div>
            <button class="text-button" type="button">Sync secrets</button>
          </div>
          <div class="vault-grid">
            <article v-for="item in vaultItems" :key="item.name">
              <strong>{{ item.name }}</strong>
              <span>{{ item.secret }}</span>
              <small>{{ item.owner }}</small>
            </article>
          </div>
        </div>
        <div class="panel wide">
          <div class="vault-flow">
            <span>OAuth2</span>
            <span>Vault</span>
            <span>Runtime</span>
            <span>Tool call</span>
            <span>Audit</span>
          </div>
        </div>
      </section>
    </main>

    <aside
      class="global-agent"
      :class="{ open: assistantOpen, dragging: isDraggingAgent }"
      :style="{ right: `${agentPosition.x}px`, bottom: `${agentPosition.y}px` }"
      aria-label="Acuaponsito floating assistant"
      @pointerdown="startAgentDrag"
    >
      <div class="agent-avatar" :class="agentMediaMode">
        <div class="agent-svg-face">
          <span></span>
          <span></span>
        </div>
      </div>
      <div class="agent-mini-copy">
        <strong>Acuaponsito</strong>
        <span>{{ userSession.role }}</span>
      </div>
      <div class="agent-expanded">
        <div>
          <span class="eyebrow">floating embed</span>
          <h3>{{ selectedAgent.role }}</h3>
          <p>{{ selectedAgent.scope }}</p>
        </div>
        <div class="agent-media-row">
          <button type="button" @click.stop="cycleAgentMedia">{{ selectedMedia?.label }}</button>
          <button type="button" @click.stop="assistantOpen = false">minimize</button>
        </div>
        <small>{{ selectedMedia?.detail }}</small>
      </div>
      <button class="agent-open-button" type="button" @click.stop="assistantOpen = !assistantOpen">
        {{ assistantOpen ? "close" : "open" }}
      </button>
    </aside>
  </div>
</template>
