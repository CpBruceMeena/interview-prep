# 🏗️ Low Level Design Problems

A comprehensive collection of **18 Low-Level Design (LLD)** problems implemented in **Python**, following **SOLID principles** and **design patterns** — curated for **6+ years experienced backend developer** interviews.

---

## 📋 Project Index

| # | Project | Focus Area | Key Design Patterns |
|---|---------|-----------|-------------------|
| 1 | [Parking Lot](parking-lot/INTERVIEW_QUESTIONS.md) | OOD Basics, Vehicle Management | Strategy, Factory, Singleton |
| 2 | [Chess Game](chess-game/INTERVIEW_QUESTIONS.md) | Game State, Complex Rules | Factory, State, Memento |
| 3 | [Tic-Tac-Toe](tic-tac-toe/INTERVIEW_QUESTIONS.md) | Simple Game, AI (Minimax) | Strategy, State, Command |
| 4 | [Snakes & Ladders](snakes-and-ladders/INTERVIEW_QUESTIONS.md) | Board Game, Dice Strategies | Strategy, Observer, State |
| 5 | [Vending Machine](vending-machine/INTERVIEW_QUESTIONS.md) | State Machine, Payments | State, Strategy, Factory |
| 6 | [LRU/LFU/TTL Cache](lru-cache/INTERVIEW_QUESTIONS.md) | Data Structures, Eviction | Strategy, Decorator |
| 7 | [Rate Limiter](rate-limiter/INTERVIEW_QUESTIONS.md) | API Rate Limiting | Strategy, Factory, Decorator |
| 8 | [Pub-Sub System](pub-sub-system/INTERVIEW_QUESTIONS.md) | Messaging, Events | Observer, Strategy, Decorator |
| 9 | [Movie Ticket Booking](movie-ticket-booking/INTERVIEW_QUESTIONS.md) | Concurrency, Booking | Strategy, Singleton, Observer |
| 10 | [Splitwise (Expense Sharing)](splitwise-expense-sharing/INTERVIEW_QUESTIONS.md) | Graphs, Debt Simplification | Strategy, Factory |
| 11 | [Cab Booking (Uber)](cab-booking-uber/INTERVIEW_QUESTIONS.md) | Real-time Matching, GeoRadius, Kafka, Zone Surge | Strategy, State, Observer, Pub-Sub |
| 12 | [Library Management](library-management/INTERVIEW_QUESTIONS.md) | Catalog, Fines, Circulation | Strategy, Observer, Facade |
| 13 | [Car Rental Platform](car-rental-platform/INTERVIEW_QUESTIONS.md) | Fleet, Availability Calendar, Hourly Booking | Strategy, State, Decorator |
| 14 | [ATM/Banking System](atm-banking-system/INTERVIEW_QUESTIONS.md) | State Machine, Security | State, Strategy, Chain of Responsibility |
| 15 | [Inventory Management](inventory-management/INTERVIEW_QUESTIONS.md) | Stock, Reorder, Warehouse | Strategy, Observer, Facade |
| 16 | [Payment Processing](payment-processing-system/INTERVIEW_QUESTIONS.md) | Payments, Refunds, Fraud | Strategy, Chain of Responsibility |
| 17 | [Job Scheduling](job-scheduling-system/INTERVIEW_QUESTIONS.md) | Scheduling, Recurring Jobs | Command, Strategy, Observer |
| 18 | [Search Platform](search-platform/INTERVIEW_QUESTIONS.md) | Indexing, Ranking, TF-IDF | Strategy, Facade, Decorator |

---

## 🎯 SOLID Principles Applied

Each project is designed following **SOLID principles**:

- **S** - **Single Responsibility**: Each class has one clear purpose
- **O** - **Open/Closed**: Open for extension, closed for modification
- **L** - **Liskov Substitution**: Subtypes are substitutable for base types
- **I** - **Interface Segregation**: Small, focused interfaces
- **D** - **Dependency Inversion**: Depend on abstractions, not concretions

---

## 🧩 Design Patterns Used

| Pattern | Usage |
|---------|-------|
| **Strategy** | Pricing, fee calculation, eviction strategies, matching algorithms |
| **Factory** | Vehicle, piece, player, document creation |
| **Observer** | Notifications, display updates, event handling |
| **State** | Vending machine, ATM, game states |
| **Facade** | Unified service interfaces |
| **Decorator** | Adding features without modifying core classes |
| **Command** | Job execution, undo/redo operations |
| **Chain of Responsibility** | Validation pipelines, fraud checks |
| **Singleton** | Cache manager, broker instance |

---

## 🚀 How to Run

Each project is self-contained. Navigate to the project directory and run:

```bash
cd low-level-design/<project-name>
python <project_file>.py
```

Or run all projects from root:

```bash
for dir in low-level-design/*/; do
    echo "=== Running $dir ==="
    cd "$dir" && python *.py && cd - > /dev/null
done
```

---

## 📖 Interview Preparation

Each project includes an `INTERVIEW_QUESTIONS.md` file with:
- Core design questions with follow-ups
- Expected solution points
- Design pattern discussions
- Trade-off analyses
- Scalability considerations

---

## 🏆 Recommended Roadmap

1. **Start with basics**: Parking Lot, Vending Machine, Tic-Tac-Toe
2. **Move to games**: Chess, Snakes & Ladders
3. **Learn data structures**: LRU Cache, Rate Limiter
4. **Build systems**: Library Management, Inventory, Car Rental
5. **Master real-world**: Splitwise, Movie Booking, Uber
6. **Advanced**: Payment Processing, Job Scheduling, Search Platform

---

## 📚 Additional Resources

- [Clean Code - Robert C. Martin](https://www.oreilly.com/library/view/clean-code-a/9780136083238/)
- [Design Patterns - GoF](https://www.oreilly.com/library/view/design-patterns-elements/0201633612/)
- [System Design Interview - Alex Xu](https://www.amazon.com/System-Design-Interview-Insiders-Guide/dp/1736049119)
