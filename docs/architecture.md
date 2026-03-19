# Architecture

## Overview
Forge v1 is a stateful design engine focused on the design layer. It refines high-level ideas into structured design artifacts and milestones.

## Key Components
1. **Vision Loader**: Loads and persists the project vision.
2. **Design Manager**: Maintains system design documents (requirements, architecture, decisions, milestones).
3. **Decision Tracker**: Records and tracks decisions made during the design process.
4. **Milestone Generator**: Generates bounded milestones based on design artifacts.
5. **Run History Manager**: Stores a history of runs for auditability and reproducibility.

## Data Flow
1. Input: High-level idea → Design artifacts (requirements, architecture, decisions, milestones).
2. Output: Structured design artifacts and milestones.

## State Management
All state is persisted in files, ensuring auditability and reproducibility.
