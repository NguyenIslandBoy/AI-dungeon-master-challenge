# AI Agent Engineering Challenge

## Overview

Welcome! We’d like you to build a small AI-powered application that demonstrates how you think about designing AI systems.

This is not a coding puzzle or an algorithm challenge. Feel free to use AI coding assistants (Cursor, Claude Code, ChatGPT, Copilot, etc.) just as you would in a real engineering environment.

We’re primarily interested in your engineering decisions, how you structure your application, and how you reason about problems.

Please aim to spend no more 3–4 hours on this challenge. We’ve intentionally designed it to fit within that timeframe. If you have additional ideas, we’d much rather read about them in your README than have you spend an entire weekend implementing them.

## The Challenge

Build an **AI Dungeon Master** that runs an interactive text adventure.

The player should be able to explore a fantasy world through natural conversation with the Dungeon Master.

As the story unfolds, the Dungeon Master should remain consistent, remember previous events, and adapt the story based on the player’s decisions.

There is no single “correct” implementation. We’re much more interested in how you approach the problem than how many features you build.

## Example

**Dungeon Master**

> You awaken in an abandoned lighthouse overlooking a stormy sea. Rain crashes against the windows. A rusty key and a sealed letter lie on a wooden table. A staircase disappears into darkness above you.
>
> What do you do?

**Player**

> I pick up the letter.

**Dungeon Master**

> The wax seal bears the crest of House Valen.
>
> Inside, someone has written:
>
> “Don’t trust the keeper.”
>
> As you finish reading, you hear slow footsteps coming from upstairs…

## Requirements

### 1. Chat Interface

Provide a simple interface for interacting with the Dungeon Master.

Examples include:

- CLI
- Web application
- Terminal UI

The focus is the AI system—not the frontend.

### 2. World Building

Create a small fantasy world.

For example:

- Locations
- Characters
- Creatures
- Items
- History
- Quests
- Factions

The Dungeon Master should use this information consistently throughout the adventure.

### 3. Player Progress

The game should remember important things that happen during the adventure.

Examples include:

- Items collected
- Places visited
- Relationships with characters
- Quests completed
- Important choices
- Significant events

The story should naturally evolve based on previous interactions.

For example:

**Early in the game:**

> “I don’t trust wizards.”

**Later…**

> The village mage notices your hesitation before offering to help.

### 4. README

Include a short README describing:

- Your architecture
- Design decisions
- Assumptions
- Trade-offs
- What you would improve if you had another day to work on the project

## Submission

Please submit:

- Source code
- README
- Instructions for running the project
- If API keys are required, include setup instructions.

## What We’re Looking For

There is no single correct solution.

We’re interested in how you think about problems such as:

- Keeping a story coherent over a long conversation
- Remembering important information while avoiding unnecessary details
- Organizing your application cleanly
- Making sensible engineering trade-offs
- Building something simple, robust, and enjoyable to use

We’re not evaluating how many features you implemented.

A thoughtful, well-designed solution is much more valuable than a large, unfinished project.

## AI Tools

You are encouraged to use AI coding assistants throughout this challenge.

Use whatever tools you normally work with.

During the interview, we’ll discuss your implementation, your design decisions, and any trade-offs you made.

We care much more about your understanding of the solution than whether every line of code was written manually.

## Have Fun

The best submissions are often the ones where the author clearly enjoyed building them.

We’re excited to see what kind of world—and Dungeon Master—you create.
