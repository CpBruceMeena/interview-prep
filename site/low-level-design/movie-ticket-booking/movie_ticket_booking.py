"""
Movie Ticket Booking System (BookMyShow) - Low Level Design
-------------------------------------------------------------
Design Principles: SOLID, Singleton, Observer, Strategy
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
import threading
import uuid


class City(Enum):
    MUMBAI = "Mumbai"
    DELHI = "Delhi"
    BANGALORE = "Bangalore"
    HYDERABAD = "Hyderabad"


class Genre(Enum):
    ACTION = "Action"
    COMEDY = "Comedy"
    DRAMA = "Drama"
    HORROR = "Horror"
    ROMANCE = "Romance"
    SCI_FI = "Sci-Fi"
    THRILLER = "Thriller"


class SeatStatus(Enum):
    AVAILABLE = "Available"
    BOOKED = "Booked"
    BLOCKED = "Blocked"


class BookingStatus(Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    REFUNDED = "Refunded"


# --- Movie (SRP) ---

class Movie:
    """Single Responsibility: Represents a movie"""

    def __init__(self, movie_id: str, title: str, genre: Genre,
                 duration_minutes: int, language: str, rating: float = 0.0):
        self._movie_id = movie_id
        self._title = title
        self._genre = genre
        self._duration = duration_minutes
        self._language = language
        self._rating = rating

    @property
    def movie_id(self) -> str:
        return self._movie_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def duration(self) -> int:
        return self._duration

    def __str__(self) -> str:
        return f"{self._title} ({self._language})"


# --- Theatre / Screen / Seat Hierarchy ---

class Seat:
    def __init__(self, seat_id: str, row: str, number: int, category: str = "Regular"):
        self._seat_id = seat_id
        self._row = row
        self._number = number
        self._category = category  # Regular, Premium, VIP
        self._status = SeatStatus.AVAILABLE

    @property
    def seat_id(self) -> str:
        return self._seat_id

    @property
    def category(self) -> str:
        return self._category

    @property
    def status(self) -> SeatStatus:
        return self._status

    @status.setter
    def status(self, value: SeatStatus) -> None:
        self._status = value

    def __str__(self) -> str:
        return f"{self._row}{self._number}"


class Screen:
    def __init__(self, screen_id: str, name: str):
        self._screen_id = screen_id
        self._name = name
        self._seats: Dict[str, Seat] = {}

    @property
    def screen_id(self) -> str:
        return self._screen_id

    @property
    def name(self) -> str:
        return self._name

    def add_seat(self, seat: Seat) -> None:
        self._seats[seat.seat_id] = seat

    def get_seat(self, seat_id: str) -> Optional[Seat]:
        return self._seats.get(seat_id)

    def get_all_seats(self) -> List[Seat]:
        return list(self._seats.values())

    def get_available_seats(self) -> List[Seat]:
        return [s for s in self._seats.values() if s.status == SeatStatus.AVAILABLE]


class Theatre:
    def __init__(self, theatre_id: str, name: str, city: City, address: str):
        self._theatre_id = theatre_id
        self._name = name
        self._city = city
        self._address = address
        self._screens: Dict[str, Screen] = {}

    @property
    def theatre_id(self) -> str:
        return self._theatre_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def city(self) -> City:
        return self._city

    def add_screen(self, screen: Screen) -> None:
        self._screens[screen.screen_id] = screen

    def get_screen(self, screen_id: str) -> Optional[Screen]:
        return self._screens.get(screen_id)


# --- Show (SRP) ---

class Show:
    """Represents a movie screening at a specific time"""

    def __init__(self, show_id: str, movie: Movie, screen: Screen,
                 theatre: Theatre, start_time: datetime):
        self._show_id = show_id
        self._movie = movie
        self._screen = screen
        self._theatre = theatre
        self._start_time = start_time
        self._end_time = start_time + timedelta(minutes=movie.duration + 15)  # 15 min buffer
        self._pricing: Dict[str, float] = {"Regular": 150.0, "Premium": 250.0, "VIP": 400.0}

    @property
    def show_id(self) -> str:
        return self._show_id

    @property
    def movie(self) -> Movie:
        return self._movie

    @property
    def screen(self) -> Screen:
        return self._screen

    @property
    def theatre(self) -> Theatre:
        return self._theatre

    @property
    def start_time(self) -> datetime:
        return self._start_time

    @property
    def end_time(self) -> datetime:
        return self._end_time

    def get_price(self, category: str) -> float:
        return self._pricing.get(category, 150.0)

    def set_pricing(self, category: str, price: float) -> None:
        self._pricing[category] = price

    def __str__(self) -> str:
        return f"{self._movie.title} at {self._theatre.name} on {self._start_time:%d %b %I:%M %p}"


# --- Pricing Strategy (Strategy Pattern - OCP) ---

class PricingStrategy(ABC):
    @abstractmethod
    def calculate_price(self, base_price: float, show: Show, category: str) -> float:
        pass


class StandardPricing(PricingStrategy):
    def calculate_price(self, base_price: float, show: Show, category: str) -> float:
        return base_price


class PeakPricing(PricingStrategy):
    def __init__(self, peak_hours: Set[int], surcharge: float = 1.5):
        self._peak_hours = peak_hours
        self._surcharge = surcharge

    def calculate_price(self, base_price: float, show: Show, category: str) -> float:
        if show.start_time.hour in self._peak_hours:
            return base_price * self._surcharge
        return base_price


class WeekendPricing(PricingStrategy):
    def __init__(self, weekend_surcharge: float = 1.25):
        self._weekend_surcharge = weekend_surcharge

    def calculate_price(self, base_price: float, show: Show, category: str) -> float:
        if show.start_time.weekday() >= 5:  # Saturday/Sunday
            return base_price * self._weekend_surcharge
        return base_price


# --- Booking (SRP) ---

class Booking:
    def __init__(self, booking_id: str, show: Show, user_id: str, seats: List[Seat]):
        self._booking_id = booking_id
        self._show = show
        self._user_id = user_id
        self._seats = seats
        self._total_amount: float = 0.0
        self._status = BookingStatus.PENDING
        self._created_at = datetime.now()
        self._lock = threading.Lock()

        # Calculate total
        for seat in seats:
            self._total_amount += show.get_price(seat.category)

    @property
    def booking_id(self) -> str:
        return self._booking_id

    @property
    def show(self) -> Show:
        return self._show

    @property
    def seats(self) -> List[Seat]:
        return self._seats

    @property
    def total_amount(self) -> float:
        return self._total_amount

    @property
    def status(self) -> BookingStatus:
        return self._status

    def confirm(self) -> None:
        with self._lock:
            if self._status != BookingStatus.PENDING:
                raise ValueError(f"Cannot confirm booking in {self._status} status")
            self._status = BookingStatus.CONFIRMED

    def cancel(self) -> None:
        with self._lock:
            if self._status != BookingStatus.CONFIRMED:
                raise ValueError(f"Cannot cancel booking in {self._status} status")
            self._status = BookingStatus.CANCELLED
            # Release seats
            for seat in self._seats:
                seat.status = SeatStatus.AVAILABLE


# --- Booking Manager (SRP) ---

class BookingManager:
    """Single Responsibility: Manages booking flow with concurrency"""

    def __init__(self, pricing_strategy: PricingStrategy = None):
        self._bookings: Dict[str, Booking] = {}
        self._pricing_strategy = pricing_strategy or StandardPricing()
        self._lock = threading.Lock()

    def create_booking(self, show: Show, user_id: str, seat_ids: List[str]) -> Booking:
        """Thread-safe seat booking with transaction-like behavior"""
        with self._lock:
            # Validate seat availability
            seats = []
            for seat_id in seat_ids:
                seat = show.screen.get_seat(seat_id)
                if not seat:
                    raise ValueError(f"Seat {seat_id} not found")
                if seat.status != SeatStatus.AVAILABLE:
                    raise ValueError(f"Seat {seat_id} is already {seat.status.value}")
                seats.append(seat)

            # Block seats
            for seat in seats:
                seat.status = SeatStatus.BLOCKED

        # Create booking
        booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
        booking = Booking(booking_id, show, user_id, seats)

        with self._lock:
            self._bookings[booking_id] = booking

        print(f"  Booking {booking_id} created for {len(seats)} seat(s) - Total: ${booking.total_amount:.2f}")
        return booking

    def confirm_booking(self, booking_id: str) -> Booking:
        booking = self._bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking {booking_id} not found")

        booking.confirm()
        # Mark seats as booked
        for seat in booking.seats:
            seat.status = SeatStatus.BOOKED
        print(f"  Booking {booking_id} confirmed!")
        return booking

    def cancel_booking(self, booking_id: str) -> Booking:
        booking = self._bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking {booking_id} not found")
        booking.cancel()
        print(f"  Booking {booking_id} cancelled. Seats released.")
        return booking

    def get_booking(self, booking_id: str) -> Optional[Booking]:
        return self._bookings.get(booking_id)


# --- Search Service (SRP) ---

class MovieSearchService:
    """Search and filter movies by various criteria"""

    def __init__(self):
        self._movies: Dict[str, Movie] = {}
        self._shows: Dict[str, Show] = {}

    def add_movie(self, movie: Movie) -> None:
        self._movies[movie.movie_id] = movie

    def add_show(self, show: Show) -> None:
        self._shows[show.show_id] = show

    def search_by_city(self, city: City) -> List[Show]:
        return [s for s in self._shows.values() if s.theatre.city == city]

    def search_by_movie(self, movie_id: str) -> List[Show]:
        return [s for s in self._shows.values() if s.movie.movie_id == movie_id]

    def search_by_genre(self, genre: Genre, city: Optional[City] = None) -> List[Show]:
        shows = self._shows.values()
        if city:
            shows = [s for s in shows if s.theatre.city == city]
        return [s for s in shows if s.movie._genre == genre]

    def search_by_date(self, date: datetime, city: Optional[City] = None) -> List[Show]:
        shows = self._shows.values()
        if city:
            shows = [s for s in shows if s.theatre.city == city]
        return [s for s in shows if s.start_time.date() == date.date()]

    def get_available_seats(self, show_id: str) -> List[Seat]:
        show = self._shows.get(show_id)
        if show:
            return show.screen.get_available_seats()
        return []


# --- Demo ---

def setup_system() -> Tuple[MovieSearchService, BookingManager]:
    search = MovieSearchService()
    manager = BookingManager(WeekendPricing())

    # Add movies
    movie1 = Movie("M1", "Inception", Genre.SCI_FI, 148, "English", 8.8)
    movie2 = Movie("M2", "The Dark Knight", Genre.ACTION, 152, "English", 9.0)
    movie3 = Movie("M3", "3 Idiots", Genre.COMEDY, 170, "Hindi", 8.4)
    search.add_movie(movie1)
    search.add_movie(movie2)
    search.add_movie(movie3)

    # Add theatres
    theatre1 = Theatre("T1", "PVR Cinemas", City.MUMBAI, "Andheri West")
    theatre2 = Theatre("T2", "INOX", City.BANGALORE, "Forum Mall")

    # Setup screens and seats
    for theatre in [theatre1, theatre2]:
        screen = Screen(f"S1_{theatre.theatre_id}", "Screen 1")
        for row in "ABCDEF":
            for num in range(1, 11):
                category = "VIP" if row <= "B" else ("Premium" if row <= "D" else "Regular")
                seat = Seat(f"{row}{num}", row, num, category)
                screen.add_seat(seat)
        theatre.add_screen(screen)

    # Add shows
    tomorrow = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    for i, movie in enumerate([movie1, movie2, movie3]):
        show = Show(f"SH{i+1}", movie, theatre1.get_screen("S1_T1"),
                    theatre1, tomorrow + timedelta(hours=3 * (i + 1)))
        search.add_show(show)

    return search, manager


def demo():
    print("=== Movie Ticket Booking System (BookMyShow) ===")
    print("=" * 50)

    search, manager = setup_system()

    # Search
    print("\n--- Search: Movies in Mumbai ---")
    shows = search.search_by_city(City.MUMBAI)
    for show in shows:
        print(f"  {show}")
        avail = show.screen.get_available_seats()
        print(f"    Available seats: {len(avail)}")

    # Book tickets
    print("\n--- Booking ---")
    show = shows[0]
    seat_ids = [s.seat_id for s in show.screen.get_available_seats()[:3]]
    print(f"  Booking '{show.movie.title}' - Seats: {', '.join(seat_ids)}")

    booking = manager.create_booking(show, "user_123", seat_ids)
    manager.confirm_booking(booking.booking_id)

    # Try booking same seats (should fail)
    print("\n--- Attempt Double Booking ---")
    try:
        manager.create_booking(show, "user_456", seat_ids[:1])
    except ValueError as e:
        print(f"  ⚠️ Double booking prevented: {e}")

    # Cancel booking
    print("\n--- Cancellation ---")
    manager.cancel_booking(booking.booking_id)

    # Verify seats are available again
    avail = show.screen.get_available_seats()
    print(f"\n  Available after cancel: {len(avail)} seats")

    print("\n✅ Demo complete!")


if __name__ == "__main__":
    demo()
