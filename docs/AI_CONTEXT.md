# AI Context

This document provides the complete engineering context for AI coding assistants working on Radius.

Every AI session should read and follow this document before generating code.

Failure to follow these guidelines may result in inconsistent architecture.

---

# About Radius

Radius is an AI-native Software Verification Platform.

It helps engineering teams determine whether a Pull Request is safe to merge.

Radius does NOT generate code.

Radius verifies code.

The long-term goal is to become the intelligence layer between software development and production deployment.

---

# Product Philosophy

Every feature must increase developer confidence.

Radius should never optimize for feature quantity.

Instead it should optimize for:

- correctness

- explainability

- maintainability

- scalability

- extensibility

Every engineering decision should support these principles.

---

# Core Question

Every subsystem in Radius ultimately contributes toward answering one question.

> Can this Pull Request be merged safely?

If a proposed feature does not improve the answer to this question, it probably does not belong in Radius.

---

# Phase 1 Goal

Phase 1 builds deterministic repository intelligence.

Artificial Intelligence should NOT make engineering decisions during Phase 1.

Repository understanding comes before AI.

The platform should understand software before attempting to generate tests or predict risk.

---

# Architecture

Radius follows a modular architecture.

Current domains include:

Repository

Parser

Graph

Analysis

Testing

Confidence

Presentation

Every domain owns a single responsibility.

Domains communicate through interfaces.

Domains should never depend directly on another domain's implementation.

---

# Development Principles

When implementing code:

Prefer readability over cleverness.

Prefer composition over inheritance.

Prefer interfaces over concrete implementations.

Prefer explicit code over magic.

Avoid global state.

Avoid circular dependencies.

Avoid tightly coupled modules.

Keep every function focused.

---

# Coding Philosophy

Every class should have one responsibility.

Every function should do one thing.

Every module should own one business capability.

Large files should be split into smaller components.

Business logic should never live inside API controllers.

Controllers coordinate.

Services execute.

Repositories persist.

Domain models represent business concepts.

---

# Technology Stack

Frontend

Next.js

React

TypeScript

TailwindCSS

shadcn/ui

Backend

FastAPI

Python

Database

PostgreSQL

ORM

SQLAlchemy

Parser

Tree-sitter

Graph

NetworkX

Git

GitPython

Authentication

GitHub App

Testing

pytest

---

# Repository Structure

apps/

dashboard/

api/

worker/

packages/

repository/

parser/

graph/

analysis/

testing/

confidence/

shared/

docs/

scripts/

infra/

.github/

Never generate new top-level folders without justification.

---

# Module Boundaries

Repository Domain

Responsible only for Git repositories.

Parser Domain

Responsible only for semantic extraction.

Graph Domain

Responsible only for relationships.

Analysis Domain

Responsible only for impact analysis.

Testing Domain

Responsible only for validation.

Confidence Domain

Responsible only for confidence scoring.

Presentation Domain

Responsible only for exposing information.

Never mix responsibilities.

---

# AI Implementation Rules

Never implement features outside the requested scope.

Never invent architecture.

Never change existing contracts.

Never rename packages without explicit approval.

Never introduce unnecessary frameworks.

Never introduce microservices.

Never add caching unless requested.

Never optimize prematurely.

---

# API Rules

Every endpoint must:

Validate input.

Return typed responses.

Handle errors gracefully.

Use consistent response models.

Avoid business logic inside routes.

---

# Database Rules

Database schema must be normalized.

Use foreign keys.

Use indexes where appropriate.

Avoid duplicated data.

Store derived values only when necessary.

---

# Error Handling

Every operation should return meaningful errors.

Never swallow exceptions.

Log unexpected failures.

Return actionable messages.

---

# Testing Rules

Every public service should have unit tests.

Integration tests should validate workflows.

Avoid testing implementation details.

Test observable behavior.

---

# Documentation Rules

Every exported class should include documentation.

Every complex algorithm should explain why it exists.

Public APIs should be documented.

Architecture decisions should be recorded.

---

# Future Compatibility

Every implementation should assume future support for:

Multiple languages

Neo4j

Distributed workers

Queues

AI test generation

Security scanning

Historical learning

Enterprise organizations

Do not hardcode assumptions that prevent these future capabilities.

---

# AI Response Style

When generating code:

Produce production-quality code.

Avoid placeholders.

Avoid TODO comments unless requested.

Prefer complete implementations.

Use descriptive naming.

Keep functions small.

Use dependency injection where appropriate.

Document public interfaces.

Follow the established architecture.

When uncertain, ask for clarification rather than making architectural assumptions.

---

# Final Principle

Radius is not a demo project.

It is intended to evolve into a production-grade software verification platform.

Every line of code should reflect that goal.