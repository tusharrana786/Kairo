CREATE TABLE IF NOT EXISTS workflow_executions (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS task_executions (
    workflow_id uuid NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    task_key text NOT NULL,
    task_type text NOT NULL,
    input jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('blocked', 'ready', 'running', 'succeeded', 'failed')),
    PRIMARY KEY (workflow_id, task_key)
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    workflow_id uuid NOT NULL,
    task_key text NOT NULL,
    depends_on text NOT NULL,
    PRIMARY KEY (workflow_id, task_key, depends_on),
    CHECK (task_key <> depends_on),
    FOREIGN KEY (workflow_id, task_key) REFERENCES task_executions(workflow_id, task_key) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id, depends_on) REFERENCES task_executions(workflow_id, task_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS task_dependencies_dependents
    ON task_dependencies (workflow_id, depends_on);
