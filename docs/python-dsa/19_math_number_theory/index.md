# Math & Number Theory

> Python implementation — 10 questions covering core concepts and interview patterns.

MATH & NUMBER THEORY — Core Concepts & Interview Questions

---

```python
"""
MATH & NUMBER THEORY — Core Concepts & Interview Questions
===========================================================

Core Concepts:
──────────────
• Prime Numbers: Sieve of Eratosthenes, primality test, prime factorization
• GCD & LCM: Euclidean algorithm (recursive + iterative)
• Modular Arithmetic: (a + b) % m, (a * b) % m, modular exponentiation
• Combinatorics: permutations, combinations, Catalan numbers
• Geometry: distance, orientation, convex hull
• Probability: expected value, random sampling, reservoir sampling

Key Algorithms:
───────────────
• Euclidean GCD: gcd(a, b) = gcd(b, a % b), O(log min(a,b))
• Sieve of Eratosthenes: O(n log log n) for primes up to n
• Fast Exponentiation (Exponentiation by Squaring): O(log n)
• Miller-Rabin: Probabilistic primality test (deterministic for 64-bit
  inputs with a fixed set of bases)
• Pollard's Rho: Integer factorization

Python notes:
• Use math.isqrt(n) for integer square roots: int(n ** 0.5) goes through a
  float and is off by one for large n (above ~2⁵²)
• Built-ins: math.gcd, math.lcm (3.9+), math.comb, pow(b, e, m) for
  modular exponentiation, pow(a, -1, m) for modular inverse (3.8+)
• Java/Go: a * b overflows long past ~9.2e18; reduce mod m before
  multiplying and keep m below ~3e9 so (m-1)² fits
"""

from typing import List, Optional, Set, Tuple
import math
import random


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Sieve of Eratosthenes (Count Primes)
# ════════════════════════════════════════════════════════════════════════

def count_primes(n: int) -> int:
    """
    QUESTION:
    ─────────
    Count the number of prime numbers less than a non-negative integer n.

    Example:
        Input: n = 10
        Output: 4  (primes: 2, 3, 5, 7)

    THOUGHT PROCESS:
    ────────────────
    1. Sieve of Eratosthenes:
       - Create boolean array of size n, initially all True
       - Mark 0 and 1 as not prime
       - For i from 2 to sqrt(n): if i is prime, mark all multiples as False
       - Count remaining True values
    2. Optimization: Start marking from i*i (not 2*i), because smaller
       multiples are already marked by smaller primes
    3. Space optimization: bytearray (1 byte per number) instead of a
       list of bools (an 8-byte pointer each); bitset or odd-only sieve
       for more
    4. Why only up to √n: a composite c < n has a prime factor ≤ √c,
       so it is already crossed out by the time i passes √n

    COMPLEXITY:
    ──────────
    Time: O(n log log n) — Sieve complexity
    Space: O(n) — Boolean array
    """
    if n < 2:
        return 0

    is_prime = [True] * n
    is_prime[0] = is_prime[1] = False

    for i in range(2, math.isqrt(n - 1) + 1):
        if is_prime[i]:
            # Mark multiples starting from i*i
            for j in range(i * i, n, i):
                is_prime[j] = False

    return sum(is_prime)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: GCD & LCM (Euclidean Algorithm)
# ════════════════════════════════════════════════════════════════════════

def gcd(a: int, b: int) -> int:
    """
    Compute GCD using Euclidean algorithm.

    THOUGHT PROCESS:
    ────────────────
    1. Euclid's algorithm: gcd(a, b) = gcd(b, a % b)
    2. Base: gcd(a, 0) = a
    3. Repeatedly replace (a, b) with (b, a % b) until b = 0
    4. Works because a and b share exactly the same common divisors as
       b and a % b (a % b = a - q·b)
    5. Why O(log): every two steps the larger number at least halves;
       consecutive Fibonacci numbers are the worst case (Lamé)

    COMPLEXITY:
    ──────────
    Time: O(log min(a, b)) — Number of divisions
    Space: O(1) — Iterative
    """
    a, b = abs(a), abs(b)   # Python's % follows the divisor's sign
    while b:
        a, b = b, a % b
    return a


def lcm(a: int, b: int) -> int:
    """
    LCM = |a * b| / gcd(a, b).

    Divide BEFORE multiplying: a // gcd(a, b) * b. Same result, but the
    intermediate stays small, which matters in Java/Go where a * b can
    overflow even though the LCM itself fits. lcm(0, x) is 0.
    """
    if a == 0 or b == 0:
        return 0
    return abs(a // gcd(a, b) * b)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Modular Exponentiation (Fast Power)
# ════════════════════════════════════════════════════════════════════════

def mod_pow(base: int, exp: int, mod: int) -> int:
    """
    QUESTION:
    ─────────
    Compute (base^exp) % mod efficiently in O(log exp).

    Example:
        Input: base=2, exp=10, mod=1000
        Output: 24  (2^10 = 1024, 1024 % 1000 = 24)

    THOUGHT PROCESS:
    ────────────────
    1. Exponentiation by squaring:
       - If exp is even: base^exp = (base^2)^(exp/2)
       - If exp is odd: base^exp = base * base^(exp-1)
    2. Each step squaring reduces exponent by half → O(log n)
    3. Apply modulo at each multiplication to keep numbers small (in
       Java/Go this prevents overflow; in Python it keeps big-int
       arithmetic fast)
    4. Python built-in: pow(base, exp, mod). Uses: RSA, hashing, and
       modular inverse via Fermat — a^(p-2) mod p when p is prime
    5. Same squaring trick on matrices gives Fibonacci in O(log n)

    COMPLEXITY:
    ──────────
    Time: O(log exp) — Number of squarings
    Space: O(1) — Iterative
    """
    result = 1 % mod   # Not plain 1: x^0 mod 1 must be 0
    base %= mod

    while exp > 0:
        if exp & 1:  # Odd exponent
            result = (result * base) % mod
        base = (base * base) % mod
        exp >>= 1  # Divide by 2

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Happy Number (Cycle Detection in Number Theory)
# ════════════════════════════════════════════════════════════════════════

def is_happy(n: int) -> bool:
    """
    QUESTION:
    ─────────
    A happy number: repeatedly replace by sum of squares of its digits.
    If it reaches 1, it's happy. If it cycles endlessly, it's not.

    Example:
        Input: 19
        Output: true
        (19 → 82 → 68 → 100 → 1)

    THOUGHT PROCESS:
    ────────────────
    1. Use Floyd's Cycle Detection (slow/fast pointer) like linked list
    2. The sequence will either reach 1 or enter a cycle
    3. If slow == fast and slow != 1, we've detected a cycle
    4. This avoids the O(cycle length) space of a "seen" hash set
    5. Why it must cycle or hit 1: for a number with d digits the next
       value is at most 81·d, so values quickly fall below 243 and stay
       in a finite set; the only unhappy cycle is 4 → 16 → 37 → 58 →
       89 → 145 → 42 → 20 → 4

    COMPLEXITY:
    ──────────
    Time: O(log n) — The first step costs O(digits); after that the
          values are small, so the rest is bounded by a constant
    Space: O(1) — Only two pointers
    """

    def sum_squares(num: int) -> int:
        total = 0
        while num:
            digit = num % 10
            total += digit * digit
            num //= 10
        return total

    slow = fast = n
    while True:
        slow = sum_squares(slow)
        fast = sum_squares(sum_squares(fast))
        if fast == 1:
            return True
        if slow == fast:
            return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Prime Factorization
# ════════════════════════════════════════════════════════════════════════

def prime_factors(n: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Return the prime factors of n in ascending order.

    Example:
        Input: 84
        Output: [2, 2, 3, 7]  (84 = 2^2 × 3 × 7)

    THOUGHT PROCESS:
    ────────────────
    1. Divide by 2 while even (handles all 2 factors)
    2. Check odd divisors i while i * i <= n (n shrinking as we go)
    3. Each time we find a divisor, divide completely — so every i that
       divides n at that point is prime (its own factors are gone)
    4. If remaining n > 1, it's a prime factor (at most one prime factor
       exceeds √n)
    5. Optimization: After 2, only check odd numbers
    6. Many queries up to N: precompute the smallest prime factor of
       every number with a sieve, then factor each in O(log n)

    COMPLEXITY:
    ──────────
    Time: O(√n) — Trial division up to the square root (stops early as
          n shrinks); exponential in the number of DIGITS, which is why
          RSA is safe
    Space: O(log n) — Number of prime factors
    """
    factors = []
    if n < 2:
        return factors

    # Count factor 2
    while n % 2 == 0:
        factors.append(2)
        n //= 2

    # Check odd factors while i <= √(remaining n)
    i = 3
    while i * i <= n:
        while n % i == 0:
            factors.append(i)
            n //= i
        i += 2

    # If n is still > 1, it's a prime factor
    if n > 1:
        factors.append(n)

    return factors


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Find All Divisors
# ════════════════════════════════════════════════════════════════════════

def get_divisors(n: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Return all divisors of n in ascending order.

    Example:
        Input: 12
        Output: [1, 2, 3, 4, 6, 12]

    THOUGHT PROCESS:
    ────────────────
    1. Check i from 1 to sqrt(n)
    2. If i divides n, add both i and n//i
    3. If i == n//i (perfect square), add only once
    4. Sort the result

    COMPLEXITY:
    ──────────
    Time: O(√n) — Check up to square root
    Space: O(d(n)) — d(n) = number of divisors, far smaller than √n in
           practice (at most 1344 for any n < 10⁹)
    """
    divisors = []
    for i in range(1, math.isqrt(n) + 1):
        if n % i == 0:
            divisors.append(i)
            if i != n // i:
                divisors.append(n // i)
    return sorted(divisors)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Integer to Roman & Roman to Integer
# ════════════════════════════════════════════════════════════════════════

def int_to_roman(num: int) -> str:
    """
    QUESTION:
    ─────────
    Convert an integer to a Roman numeral.

    Example:
        Input: 1994
        Output: "MCMXCIV"

    THOUGHT PROCESS:
    ────────────────
    1. Greedy: Use the largest possible symbol at each step (safe here
       because the symbol set, with subtractive pairs, is canonical)
    2. Map values to symbols in descending order
    3. Subtract the value from num as many times as possible
    4. Include subtractive combinations (CM, CD, XC, XL, IX, IV)

    COMPLEXITY:
    ──────────
    Time: O(1) — At most 13 iterations for 3999
    Space: O(1) — Constant output length
    """
    values = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")
    ]

    result = []
    for val, symbol in values:
        while num >= val:
            result.append(symbol)
            num -= val

    return ''.join(result)


def roman_to_int(s: str) -> int:
    """
    Convert Roman numeral to integer.

    Scan right to left: a symbol smaller than the one to its right is
    subtracted (the I in IV), otherwise added. Assumes valid input; it
    does not reject malformed numerals like "IIII" or "IC".

    Time: O(n), Space: O(1)
    """
    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50,
                 'C': 100, 'D': 500, 'M': 1000}

    total = 0
    prev_value = 0

    for char in reversed(s):  # Process right to left
        value = roman_map[char]
        if value < prev_value:
            total -= value  # Subtraction case (e.g., IV = 5 - 1)
        else:
            total += value
        prev_value = value

    return total


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Pascal's Triangle
# ════════════════════════════════════════════════════════════════════════

def generate_pascal_triangle(num_rows: int) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Generate the first numRows of Pascal's triangle.

    Example:
        Input: 5
        Output: [[1],[1,1],[1,2,1],[1,3,3,1],[1,4,6,4,1]]

    THOUGHT PROCESS:
    ────────────────
    1. Each row starts and ends with 1
    2. For each position j (1 to row-1), value = prev_row[j-1] + prev_row[j]
    3. This is also C(n,k) = n! / (k! * (n-k)!)

    COMPLEXITY:
    ──────────
    Time: O(numRows²) — Total elements = n(n+1)/2
    Space: O(numRows²) — Storing all rows
    """
    triangle = []

    for row in range(num_rows):
        new_row = [1] * (row + 1)
        for j in range(1, row):
            new_row[j] = triangle[row - 1][j - 1] + triangle[row - 1][j]
        triangle.append(new_row)

    return triangle


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Reservoir Sampling (Random Pick with Uniform Probability)
# ════════════════════════════════════════════════════════════════════════

def reservoir_sample(stream: List[int], k: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Choose k elements uniformly at random from a stream of unknown size.
    Each element must have equal probability of being selected.

    Example:
        Input: stream = [1,2,3,4,5,6,7], k = 3
        Output: (random 3 elements)

    THOUGHT PROCESS:
    ────────────────
    1. Fill reservoir with first k elements
    2. For i from k to n-1:
       - Randomly pick index j in [0, i]
       - If j < k, replace reservoir[j] with stream[i]
    3. Proof (n = final stream length, indices from 0):
       - Element i (i >= k) enters with probability k/(i+1)
       - At a later step t it is evicted only if j == its slot:
         probability 1/(t+1), so it survives with t/(t+1)
       - P(i in final) = k/(i+1) · (i+1)/(i+2) · ... · (n-1)/n = k/n
       - The first k elements telescope the same way to k/n
    4. Use it when n is unknown or the data doesn't fit in memory (log
       streams, sampling rows in one pass). For a list already in
       memory, random.sample(population, k) is simpler.
    5. Weighted version: key = random() ** (1 / weight), keep the k
       largest keys (Efraimidis-Spirakis)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through the stream
    Space: O(k) — Reservoir size
    """
    if k <= 0:
        return []

    reservoir = list(stream[:k])  # Fewer than k items → return them all

    for i in range(k, len(stream)):
        # Random index from 0 to i
        j = random.randint(0, i)
        if j < k:
            reservoir[j] = stream[i]

    return reservoir


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Count Primes in Range using Segmented Sieve
# ════════════════════════════════════════════════════════════════════════

def segmented_sieve(low: int, high: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Find all primes in range [low, high] using segmented sieve.
    Useful when the range is small but the high value is large
    (can't fit all numbers in memory).

    Example:
        Input: low=10, high=30
        Output: [11, 13, 17, 19, 23, 29]

    THOUGHT PROCESS:
    ────────────────
    1. Find all primes up to sqrt(high) using simple sieve
    2. Create a boolean array for [low, high]
    3. For each prime p from step 1, mark multiples in the range
       Start from max(p*p, ((low + p - 1) // p) * p)
    4. This avoids O(high) memory — only O(sqrt(high) + range)
    5. A p*p start is needed so that p itself (when low <= p) is not
       crossed out as a multiple of itself

    COMPLEXITY:
    ──────────
    Time: O(sqrt(high) log log sqrt(high) + (high-low) log log high)
    Space: O(sqrt(high) + (high - low))
    """
    if low < 2:
        low = 2
    if high < 2:
        return []

    limit = math.isqrt(high) + 1

    # Simple sieve to find primes up to sqrt(high)
    is_prime_small = [True] * limit
    is_prime_small[0] = is_prime_small[1] = False

    for i in range(2, math.isqrt(limit - 1) + 1):
        if is_prime_small[i]:
            for j in range(i * i, limit, i):
                is_prime_small[j] = False

    primes = [i for i in range(2, limit) if is_prime_small[i]]

    # Segmented sieve for [low, high]
    n = high - low + 1
    mark = [True] * n

    for p in primes:
        # Find the first multiple of p in [low, high]
        start = max(p * p, ((low + p - 1) // p) * p)
        for j in range(start, high + 1, p):
            mark[j - low] = False

    return [i + low for i in range(n) if mark[i]]


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("MATH & NUMBER THEORY — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Count Primes (Sieve)")
    print("-" * 40)
    print(f"   Primes < 30: {count_primes(30)}")
    print(f"   Primes up to 30: {segmented_sieve(2, 30)}")

    # Q2
    print("\n2️⃣  GCD & LCM")
    print("-" * 40)
    a, b = 48, 18
    g = gcd(a, b)
    print(f"   gcd({a}, {b}) = {g}")
    print(f"   lcm({a}, {b}) = {lcm(a, b)}")
    print(f"   Check: {a} * {b} = {g} * {lcm(a, b)} = {g * lcm(a, b)}")

    # Q3
    print("\n3️⃣  Modular Exponentiation")
    print("-" * 40)
    print(f"   2^10 mod 1000 = {mod_pow(2, 10, 1000)}")
    print(f"   5^117 mod 19 = {mod_pow(5, 117, 19)}")

    # Q4
    print("\n4️⃣  Happy Number")
    print("-" * 40)
    for num in [19, 2, 7]:
        print(f"   {num}: {is_happy(num)}")

    # Q5
    print("\n5️⃣  Prime Factorization")
    print("-" * 40)
    for n in [84, 97, 100]:
        print(f"   {n}: {prime_factors(n)}")

    # Q6
    print("\n6️⃣  Divisors")
    print("-" * 40)
    for n in [12, 28, 100]:
        print(f"   Divisors of {n}: {get_divisors(n)}")

    # Q7
    print("\n7️⃣  Integer ↔ Roman")
    print("-" * 40)
    for num in [1994, 58, 3999]:
        roman = int_to_roman(num)
        back = roman_to_int(roman)
        print(f"   {num} → \"{roman}\" → {back}")

    # Q8
    print("\n8️⃣  Pascal's Triangle")
    print("-" * 40)
    rows = 5
    tri = generate_pascal_triangle(rows)
    print(f"   {rows} rows:")
    for row in tri:
        print(f"     {row}")

    # Q9
    print("\n9️⃣  Reservoir Sampling")
    print("-" * 40)
    stream = list(range(1, 101))
    sample = reservoir_sample(stream, 5)
    print(f"   Sampled {len(sample)} from {len(stream)}: {sorted(sample)}")

    # Q10
    print("\n🔟  Segmented Sieve")
    print("-" * 40)
    print(f"   Primes in [10, 30]: {segmented_sieve(10, 30)}")
    print(f"   Primes in [100, 120]: {segmented_sieve(100, 120)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
