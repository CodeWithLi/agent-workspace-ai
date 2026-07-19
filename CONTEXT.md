# Agent Workspace Collaboration

This context defines how human teams and AI specialists collaborate on project delivery and interactive product decisions.

## Language

**Agent**:
A versioned AI specialist with a defined professional role, operating policy and permitted capabilities.
_Avoid_: Bot, AI employee

**Team Discussion**:
A conversational deliberation in which several Agents challenge and synthesize a user request without changing project state.
_Avoid_: Workflow, orchestration run

**Delivery Workflow**:
A durable project delivery process that creates traceable artifacts and may change project state after passing its gates.
_Avoid_: Team Discussion, chat

**Execution Plan**:
The validated objective, specialist assignments, expected deliverables and success criteria for one Delivery Workflow.
_Avoid_: Prompt, task list

**Team Performance Profile**:
A frozen, same-project history of observed Specialist Branch delivery behavior, comparable by both Agent configuration and Capability Context.
_Avoid_: SLO, execution guarantee, cross-project benchmark

**Capability Context**:
The normalized, exact set of required capabilities assigned to one Specialist Branch. Role aggregates explain team history; only an exact Capability Context may influence candidate reliability, cost or latency.
_Avoid_: Role, objective, Prompt, task description

**Specialist Branch**:
An independently executable assignment in an Execution Plan whose result can be produced concurrently with other branches.
_Avoid_: Agent, workflow node

**Handoff**:
A Specialist Branch result that identifies its owner, objective, promised deliverable, revision round and substantive output.
_Avoid_: Message, response

**Quality Gate**:
A recorded decision that evaluates Handoffs against deterministic checks and specialist review before delivery may proceed.
_Avoid_: Test output, approval

**Revision Round**:
One bounded attempt to improve failed Handoffs using the issues recorded by a Quality Gate.
_Avoid_: Retry, rerun

**Approval Gate**:
A point where a human explicitly supplies a decision or revision direction before the Delivery Workflow continues.
_Avoid_: Quality Gate, pause

**Saga**:
The reversible record of project-changing operations performed by a Delivery Workflow.
_Avoid_: Workflow, transaction

**Product Prototype**:
A safe, structured and interactive representation of a product flow associated with a project or requirement.
_Avoid_: Generated HTML, mockup image

**Prototype Version**:
An immutable Product Prototype generation that preserves its source request, Agent trace and quality evidence.
_Avoid_: Draft, snapshot

**Redacted Evidence**:
A reviewable representation of production feedback in which personal identifiers and secrets are replaced while the protected source record remains authoritative.
_Avoid_: Raw feedback, anonymized data

**Failure Cluster**:
A role-scoped group of active negative feedback that represents the same recurring Agent behavior or unmet user expectation.
_Avoid_: Error bucket, feedback tag

**Regression Coverage**:
The degree to which Failure Clusters are represented by enabled evaluation cases that can prevent the same behavior from being released again.
_Avoid_: Role coverage, test count
