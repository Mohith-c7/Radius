<div align="center">

# ShipSafe

### The confidence layer for AI-written code.

Analyze code changes, predict regression risks, generate targeted tests, and help engineering teams ship AI-generated code with confidence.

![Status](https://img.shields.io/badge/status-active%20development-orange)
![Python](https://img.shields.io/badge/backend-FastAPI-blue)
![Next.js](https://img.shields.io/badge/frontend-Next.js-black)
![License](https://img.shields.io/badge/license-All%20Rights%20Reserved-red)

</div>

---

## Overview

Modern software is increasingly written with the help of AI coding assistants such as Cursor, Claude Code, GitHub Copilot, Gemini CLI, and Codex.

While AI accelerates development, it also introduces a new challenge:

> **How do you know AI-written code is actually safe to merge?**

Traditional testing tools only execute existing tests. They don't understand the impact of a change, predict what might break, or intelligently generate new tests where coverage is missing.

ShipSafe aims to solve that problem.

It acts as an intelligent verification layer between AI-generated code and production deployments.

---

# Why ShipSafe?

Instead of simply asking

> "Did the tests pass?"

ShipSafe asks

- What changed?
- Which modules are affected?
- What is the blast radius?
- Which existing tests should run?
- Which new tests should be generated?
- Did the behavior change unexpectedly?
- How confident are we that this PR is safe?

The result is a single explainable confidence report before every merge.

---

# Core Features

- Repository analysis
- Dependency graph generation
- Blast radius computation
- Intelligent regression detection
- AI-powered test generation
- Behavior snapshot comparison
- Confidence scoring
- GitHub Pull Request integration
- Explainable AI reports
- Security-aware validation (planned)

---

# Example Workflow

```text
Developer / AI Agent

        │
        ▼

Push Commit / Open PR

        │
        ▼

Repository Analysis

        │
        ▼

Dependency Graph

        │
        ▼

Blast Radius Analysis

        │
        ▼

Run Existing Tests

        │
        ▼

Generate Missing Tests

        │
        ▼

Regression Detection

        │
        ▼

Confidence Report

        │
        ▼

Safe to Merge ✅
```

---

# Project Structure

```text
shipsafe/

apps/
├── api/                 # FastAPI backend
├── dashboard/           # Next.js dashboard
├── worker/              # Background workers

packages/
├── ai/                  # AI providers & prompt orchestration
├── analyzer/            # Blast radius engine
├── confidence/          # Confidence scoring engine
├── database/            # Database models
├── github/              # GitHub App integration
├── graph/               # Dependency graph
├── parser/              # AST & repository parsing
├── shared/              # Shared utilities
└── ui/                  # Shared frontend components

docs/
├── architecture.md
├── roadmap.md
├── api.md
├── decisions.md
└── milestones.md

scripts/
infra/
.github/
```

---

# Technology Stack

## Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui

## Backend

- FastAPI
- Python

## AI

- Gemini
- OpenAI
- Anthropic (planned)

## Code Analysis

- Tree-sitter
- NetworkX
- Neo4j (planned)

## Database

- PostgreSQL

## Infrastructure

- Docker
- Turborepo
- pnpm

---

# MVP Scope

The initial version focuses on solving one problem well.

- Parse repositories
- Build dependency graph
- Detect affected components
- Run relevant tests
- Generate missing regression tests
- Produce an explainable confidence report

---

# Roadmap

## Phase 1

- Repository parsing
- Dependency graph
- Blast radius analysis
- GitHub App
- Confidence report

## Phase 2

- AI-generated tests
- Coverage analysis
- Mutation testing
- Behavior snapshots

## Phase 3

- Security analysis
- CodeQL integration
- Security-aware test generation

## Phase 4

- Learning confidence engine
- Historical release intelligence
- Multi-repository analysis

---

# Repository Status

| Module | Status |
|---------|--------|
| Monorepo | ✅ |
| Dashboard | 🚧 |
| Backend API | 🚧 |
| Repository Parser | ⏳ |
| Dependency Graph | ⏳ |
| Blast Radius Engine | ⏳ |
| Regression Engine | ⏳ |
| AI Test Generator | ⏳ |
| GitHub App | ⏳ |

---

# Development

Clone the repository

```bash
git clone https://github.com/your-org/shipsafe.git
```

Install dependencies

```bash
pnpm install
```

Run development servers

```bash
pnpm dev
```

---

# Vision

Our goal is to become the verification layer for AI software engineering.

As AI writes more code, developers need more than code generation—they need confidence that every change is safe.

ShipSafe aims to provide that confidence.

---

# Contributing

The project is currently in active development and is not accepting external contributions.

---

# License

This project is currently proprietary.

No license has been granted for redistribution or commercial use.

---

<div align="center">

**Built for developers who ship with AI.**

</div>