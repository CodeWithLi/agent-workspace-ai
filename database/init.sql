CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(30) DEFAULT 'member',
    is_active BOOLEAN DEFAULT true,
    permissions TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash VARCHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address VARCHAR(64) DEFAULT '',
    user_agent VARCHAR(300) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_refresh_token_hash ON user_sessions(refresh_token_hash);
CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    members TEXT DEFAULT '',
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_members (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(30) NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_project_member UNIQUE (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_project_members_project_id ON project_members(project_id);
CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members(user_id);

CREATE TABLE IF NOT EXISTS requirements (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'NEW',
    analysis TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agents (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    role VARCHAR(50) UNIQUE NOT NULL,
    description TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model VARCHAR(100) DEFAULT 'glm-4-flash',
    tools VARCHAR(500) DEFAULT '',
    memory_enable BOOLEAN DEFAULT true,
    knowledge_access BOOLEAN DEFAULT true,
    human_approval_required BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_tools (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    enabled BOOLEAN DEFAULT true,
    allowed_roles VARCHAR(200) DEFAULT 'admin,member'
);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) DEFAULT 'New conversation',
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    tool_name VARCHAR(100) NOT NULL,
    input_json TEXT DEFAULT '{}',
    result_json TEXT DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'PENDING',
    approved_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_agent_actions_user_id ON agent_actions(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_actions_project_id ON agent_actions(project_id);
CREATE INDEX IF NOT EXISTS ix_agent_actions_agent_id ON agent_actions(agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_actions_conversation_id ON agent_actions(conversation_id);
CREATE INDEX IF NOT EXISTS ix_agent_actions_status ON agent_actions(status);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(30) NOT NULL,
    content TEXT NOT NULL,
    tool_calls TEXT DEFAULT '[]',
    thinking TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    priority VARCHAR(30) DEFAULT 'MEDIUM',
    status VARCHAR(30) DEFAULT 'TODO',
    assignee_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    due_date VARCHAR(50) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) DEFAULT 'application/octet-stream',
    storage_path VARCHAR(500) NOT NULL,
    status VARCHAR(30) DEFAULT 'INDEXED',
    summary TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    vector_id VARCHAR(100),
    vector_json TEXT DEFAULT '[]',
    score_hint DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    transcript TEXT NOT NULL,
    summary TEXT DEFAULT '',
    action_items TEXT DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    recipient_email VARCHAR(255) DEFAULT '',
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    channel VARCHAR(50) DEFAULT 'email',
    schedule_at VARCHAR(50) DEFAULT '',
    scheduled_for TIMESTAMPTZ,
    status VARCHAR(30) DEFAULT 'DRAFT',
    attempts INTEGER DEFAULT 0,
    locked_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    last_error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_notifications_recipient_user_id ON notifications(recipient_user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_scheduled_for ON notifications(scheduled_for);

CREATE TABLE IF NOT EXISTS memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    memory_type VARCHAR(30) DEFAULT 'project',
    key VARCHAR(100) NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(30) DEFAULT 'RUNNING',
    current_node VARCHAR(100) DEFAULT 'requirement',
    state_json TEXT DEFAULT '{}',
    human_feedback TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(60) DEFAULT '',
    resource_id VARCHAR(100) DEFAULT '',
    details TEXT DEFAULT '{}',
    ip_address VARCHAR(64) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_project_id ON audit_logs(project_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs(created_at);
