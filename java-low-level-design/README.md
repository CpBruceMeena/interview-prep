# ☕ Java Low Level Design Problems

A collection of **3 Low-Level Design (LLD)** problems implemented in **Java**, following **SOLID principles** and **design patterns** — curated for backend developer interviews.

## 📋 Project Index

| # | Project | Domain | Key Patterns |
|---|---------|--------|-------------|
| 1 | [Elevator System](elevator-system/) | State Machine | State, Strategy, Observer |
| 2 | [Hotel Booking System](hotel-booking-system/) | Reservations | Strategy, Factory, Observer |
| 3 | [Meeting Scheduler](meeting-scheduler/) | Calendar | Strategy, Observer, Command |

## 🚀 How to Run

Each project is self-contained. Navigate to the project directory and compile/run:

```bash
cd java-low-level-design/<project-name>
javac <MainClass>.java
java <MainClass>
```

## 🧩 Design Patterns Used

| Pattern | Usage |
|---------|-------|
| **Strategy** | Dispatching, pricing, booking policies |
| **Observer** | Notifications, monitoring, calendar sync |
| **State** | Elevator lifecycle, booking status |
| **Facade** | Unified service interfaces |
| **Command** | Request objects, undoable operations |
| **Decorator** | Compose pricing modifiers |

## 📖 Interview Preparation

Each project includes:
- **THOUGHT_PROCESS.md** — Design reasoning and trade-offs
- **CODE.md** — Implementation walkthrough with code snippets
- **HIGH_LEVEL_DESIGN.md** — Production architecture and scale
- **INTERVIEW_QUESTIONS.md** — Common interview questions with answers
