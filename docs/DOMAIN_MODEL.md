# Domain Model

Project: Radius

Version: 1.0

---

# Overview

The Radius platform is built around a set of business domains.

Each domain represents a distinct capability within the software verification pipeline.

The domain model defines the core business concepts that exist independently of any programming language, framework, API, or database implementation.

Every entity described in this document represents a real-world concept within Radius.

Database tables, REST APIs, and frontend models should all derive from this domain model.

---

# Core Domain

The core business capability of Radius is software verification.

The platform evaluates software changes and determines whether they are safe to merge.

Everything within Radius ultimately contributes toward this capability.

---

# Primary Domains

Radius contains the following business domains.

Repository

↓

Pull Request

↓

Analysis

↓

Dependency Graph

↓

Testing

↓

Confidence

Each domain owns its own entities.

---

# Repository Domain

Represents a software project.

## Repository

Represents a Git repository connected to Radius.

Attributes

- id
- name
- provider
- defaultBranch
- cloneUrl
- visibility
- status
- createdAt
- updatedAt

Relationships

Repository

contains

Branches

Commits

Pull Requests

Analyses

---

## Branch

Represents a Git branch.

Attributes

- id
- repositoryId
- name
- latestCommit

---

## Commit

Represents a Git commit.

Attributes

- hash
- author
- timestamp
- message

---

# Pull Request Domain

Represents a proposed software change.

## Pull Request

Attributes

- id
- repositoryId
- title
- description
- sourceBranch
- targetBranch
- status

Relationships

Pull Request

creates

Analysis

---

# Analysis Domain

Represents one execution of Radius.

Every Pull Request creates one or more analyses.

---

## Analysis

Attributes

- id
- repositoryId
- pullRequestId
- startedAt
- completedAt
- status

Relationships

Analysis owns

Blast Radius

Confidence

Test Results

Metadata

---

# Parser Domain

Represents semantic understanding.

---

## Source File

Attributes

- path

- language

- checksum

---

## Symbol

Represents

Class

Interface

Function

Method

Variable

Enum

Namespace

Attributes

- name

- type

- visibility

- location

---

# Graph Domain

Represents software relationships.

---

## Node

Represents

File

Module

Class

Function

API

Database

---

## Edge

Represents relationships.

Examples

imports

calls

inherits

implements

references

depends_on

---

# Blast Radius Domain

Represents software impact.

---

## Blast Radius

Attributes

Affected Files

Affected Symbols

Affected APIs

Affected Tests

Dependency Depth

---

# Testing Domain

Represents validation.

---

## Test Case

Represents one executable test.

Attributes

Name

Framework

Location

---

## Test Run

Represents one execution.

Attributes

Started

Completed

Status

Duration

Logs

Coverage

---

# Confidence Domain

Represents engineering confidence.

---

## Confidence Report

Contains

Overall Score

Risk Level

Evidence

Recommendations

Summary

---

# Relationships

Repository

↓

Pull Request

↓

Analysis

↓

Blast Radius

↓

Test Run

↓

Confidence Report

---

# Aggregate Roots

Repository

Pull Request

Analysis

These become aggregate roots within the domain model.

All other entities belong beneath these aggregates.

---

# Value Objects

RepositoryId

CommitHash

BranchName

FilePath

Language

ConfidenceScore

RiskLevel

CoveragePercentage

These should be immutable.

---

# Domain Services

Repository Service

Parser Service

Graph Service

Analysis Service

Testing Service

Confidence Service

Each service contains business logic that does not naturally belong inside an entity.

---

# Domain Events

RepositoryConnected

RepositoryUpdated

PullRequestOpened

AnalysisStarted

RepositoryParsed

GraphUpdated

BlastRadiusComputed

TestsExecuted

ConfidenceCalculated

AnalysisCompleted

Future implementations should use these events for decoupled communication.

---

# Ubiquitous Language

Repository

Analysis

Blast Radius

Dependency

Confidence

Verification

Evidence

Impact

Validation

These terms should be used consistently across code, APIs, documentation, and UI.

---

# Summary

The domain model defines the business concepts of Radius independently of implementation details.

All future APIs, database schemas, frontend models, and services should derive from this model rather than introducing new concepts.