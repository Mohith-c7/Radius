# 04_System_Architecture.md

# System Architecture

**Project:** Radius

**Document Version:** 1.0

---

# Overview

Radius is designed as a modular software verification platform.

Rather than implementing all functionality inside a single application, Radius is composed of multiple independent subsystems, each responsible for a specific stage of the verification pipeline.

Every subsystem has one responsibility.

Every subsystem communicates through well-defined interfaces.

This architecture allows individual components to evolve independently while maintaining a predictable system behavior.

---

# Architectural Goals

The architecture is designed around the following goals.

- High modularity
- Loose coupling
- Scalability
- Extensibility
- Explainability
- Maintainability
- Incremental analysis
- AI-ready architecture

---

# Architectural Principles

Radius follows several architectural principles.

## Single Responsibility

Every service exists for one purpose only.

For example:

Parser → Understand source code

Graph Engine → Understand relationships

Blast Radius Engine → Understand impact

Confidence Engine → Evaluate evidence

No service should perform multiple unrelated tasks.

---

## Pipeline Architecture

The entire verification process is implemented as a sequential processing pipeline.

Every stage receives structured input from the previous stage.

Every stage produces structured output for the next stage.

This ensures predictable execution and easy debugging.

---

## Stateless Services

Services should not maintain internal state.

All persistent information should be stored in the database.

This simplifies scaling and improves reliability.

---

## Interface-Driven Design

Every package communicates through interfaces rather than implementation details.

For example:

Parser should not know how graphs are implemented.

Blast Radius Engine should not know how repositories are cloned.

Dashboard should never directly access parser internals.

---

## Incremental Processing

The system should avoid unnecessary computation.

Whenever possible:

- Parse only modified files
- Update only affected graph nodes
- Execute only affected tests
- Recompute only impacted metrics

This allows Radius to scale efficiently.

---

# High-Level Architecture

                    GitHub
                       │
                       ▼
             GitHub Webhook
                       │
                       ▼
             Repository Service
                       │
                       ▼
             Git Change Analyzer
                       │
                       ▼
               Parser Engine
                       │
                       ▼
          Repository Metadata Store
                       │
                       ▼
           Dependency Graph Engine
                       │
                       ▼
            Blast Radius Engine
                       │
                       ▼
          Test Selection Engine
                       │
                       ▼
          Test Execution Engine
                       │
                       ▼
           Confidence Engine
                       │
                       ▼
                REST API
                       │
                       ▼
            Next.js Dashboard

The Git Change Analyzer runs early to determine which files need focused work.
Parser and graph outputs remain the deterministic foundation for changed-symbol detection, blast radius computation, test selection, and confidence scoring.
