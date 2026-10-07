"""
BIT MANIPULATION — Core Concepts & Interview Questions
=======================================================

Core Concepts:
──────────────
• Bits are the fundamental unit of data — 0 or 1
• Bitwise operators:
  - & (AND): Both bits 1 → 1
  - | (OR): At least one 1 → 1
  - ^ (XOR): Bits different → 1
  - ~ (NOT): Flip all bits (in Python ~x == -x - 1)
  - << (LEFT SHIFT): Multiply by 2^k
  - >> (RIGHT SHIFT): Divide by 2^k, rounding toward -∞ (arithmetic
    shift: the sign bit is copied in). Java/JS also have >>> (logical
    shift, fills with 0); Go uses the type: >> on uint is logical
• Two's complement: -x = ~x + 1
• PYTHON GOTCHA: ints are unbounded and behave like two's complement
  with infinitely many sign bits. A negative number has infinitely many
  1s, so "loop until n == 0" never ends and bin(-5) is '-0b101'.
  To emulate a 32-bit int: mask with x & 0xFFFFFFFF, and convert back
  with x - (1 << 32) if x >= 1 << 31
• Shifting a 32-bit int by >= 32: Java masks the count to 5 bits
  (1 << 32 == 1), C makes it undefined behaviour, Go defines it as if
  shifted one bit at a time (result 0, or -1 for negative >>)
• XOR properties:
  - x ^ x = 0 (self-cancellation)
  - x ^ 0 = x (identity)
  - x ^ y = y ^ x (commutative)
  - (x ^ y) ^ z = x ^ (y ^ z) (associative)

Key Tricks:
───────────
• Check if bit at position i is set: (num >> i) & 1
• Set bit at position i: num | (1 << i)
• Clear bit at position i: num & ~(1 << i)
• Toggle bit at position i: num ^ (1 << i)
• Get lowest set bit: num & -num
• Remove lowest set bit: num & (num - 1)
• Check if power of 2: num > 0 and (num & (num - 1)) == 0
• Count set bits (Brian Kernighan): while n: n &= n - 1; count += 1
  (built in: int.bit_count() since Python 3.10, Integer.bitCount in Java,
  bits.OnesCount in Go — all compile to a POPCNT instruction where
  available)
"""

from typing import List, Optional


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Single Number
# ════════════════════════════════════════════════════════════════════════

def single_number(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given a non-empty array where every element appears twice except
    for one, find that single one. Must be O(n) time and O(1) space.

    Example:
        Input: [4, 1, 2, 1, 2]
        Output: 4

    THOUGHT PROCESS:
    ────────────────
    1. XOR all numbers together
    2. x ^ x = 0 (identical pairs cancel out)
    3. x ^ 0 = x (the unique number remains)
    4. O(n) time, O(1) space — optimal

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through array
    Space: O(1) — Single variable
    """
    result = 0
    for num in nums:
        result ^= num
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Single Number II (Every element appears three times)
# ════════════════════════════════════════════════════════════════════════

def single_number_ii(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array where every element appears three times except one,
    find the single one.

    Example:
        Input: [2, 2, 3, 2]
        Output: 3

    THOUGHT PROCESS:
    ────────────────
    1. Count bits: For each bit position, sum all bits across numbers
    2. If sum % 3 == 1, that bit is set in the single number
    3. This works because bits from tripled numbers are divisible by 3
       (generalises to "every element appears k times": use % k)
    4. Alternative (implemented): a per-bit counter mod 3 stored in two
       bitmasks (ones, twos) — state 00 → 01 → 10 → 00 for each bit
       - ones = bits seen 1 (mod 3) times; twos = bits seen 2 times
       - ones = (ones ^ num) & ~twos; twos = (twos ^ num) & ~ones
       - After three occurrences a bit is back to 00
    5. Negative inputs work in Python because ~ and & act on the
       infinite two's complement form; with the bit-count method you must
       treat bit 31 as the sign bit and convert back.

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Two variables
    """
    ones = twos = 0

    for num in nums:
        # XOR with ones, but clear bits that are in twos
        ones = (ones ^ num) & ~twos
        # XOR with twos, but clear bits that are in ones
        twos = (twos ^ num) & ~ones

    return ones


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Number of 1 Bits (Hamming Weight)
# ════════════════════════════════════════════════════════════════════════

def hamming_weight(n: int) -> int:
    """
    QUESTION:
    ─────────
    Write a function that takes an unsigned integer and returns the
    number of '1' bits it has (Hamming weight / popcount).

    Example:
        Input: 11 (binary: 1011)
        Output: 3

    THOUGHT PROCESS:
    ────────────────
    1. Brian Kernighan's algorithm:
       - n & (n - 1) removes the lowest set bit
       - Count how many times we can do this before n = 0
    2. Why n & (n-1) removes lowest set bit:
       - n = ...1000, n-1 = ...0111
       - n & (n-1) = ...0000 — lowest set bit cleared!

    3. The input is UNSIGNED 32-bit. Java passes it as a signed int, so
       inputs with the top bit set arrive negative. In Python a negative
       n would loop forever (infinitely many 1 bits), so mask first.

    COMPLEXITY:
    ──────────
    Time: O(k) — k = number of set bits (≤ 32)
    Space: O(1) — Constant
    """
    n &= 0xFFFFFFFF  # Treat as unsigned 32-bit (no-op for valid input)
    count = 0
    while n:
        n &= n - 1  # Remove lowest set bit
        count += 1
    return count


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Counting Bits (For numbers 0 to n)
# ════════════════════════════════════════════════════════════════════════

def count_bits(n: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an integer n, return an array ans of length n+1 such that
    ans[i] is the number of 1 bits in the binary representation of i.

    Example:
        Input: n = 5
        Output: [0, 1, 1, 2, 1, 2]
        Explanation: 0→0, 1→1, 2→10, 3→11, 4→100, 5→101

    THOUGHT PROCESS:
    ────────────────
    1. Brute force: Count bits for each number — O(n log n)
    2. DP reusing smaller answers (both are O(1) per i):
       - bits(i) = bits(i >> 1) + (i & 1)       — drop the last bit
       - bits(i) = bits(i & (i - 1)) + 1        — drop the lowest SET bit
    3. Example of the second: bits(5) = bits(5 & 4) + 1 = bits(4) + 1 = 2

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass with O(1) per element
    Space: O(n) — Output array
    """
    result = [0] * (n + 1)

    for i in range(1, n + 1):
        result[i] = result[i >> 1] + (i & 1)
        # Or: result[i] = result[i & (i - 1)] + 1

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Reverse Bits
# ════════════════════════════════════════════════════════════════════════

def reverse_bits(n: int) -> int:
    """
    QUESTION:
    ─────────
    Reverse bits of a given 32-bit unsigned integer.

    Example:
        Input: 43261596 (binary: 00000010100101000001111010011100)
        Output: 964176192 (binary: 00111001011110000010100101000000)

    THOUGHT PROCESS:
    ────────────────
    1. Extract bit by bit and build result
    2. For each bit position i (0 to 31):
       - Extract bit at position i: (n >> i) & 1
       - Place it at position (31-i): result |= bit << (31-i)
    3. This reverses the 32-bit representation
    4. Follow-up "called many times": reverse each byte via a 256-entry
       lookup table, or swap halves with masks in log₂32 = 5 steps
       (swap 16-bit halves, then 8-bit, 4, 2, 1)

    COMPLEXITY:
    ──────────
    Time: O(1) — Always 32 iterations
    Space: O(1)
    """
    result = 0
    for i in range(32):
        bit = (n >> i) & 1
        result |= bit << (31 - i)
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Power of Two
# ════════════════════════════════════════════════════════════════════════

def is_power_of_two(n: int) -> bool:
    """
    QUESTION:
    ─────────
    Given an integer n, return true if it is a power of two.

    Example:
        Input: 16
        Output: true
        Input: 18
        Output: false

    THOUGHT PROCESS:
    ────────────────
    1. Powers of 2 have exactly one bit set
    2. n & (n - 1) removes the lowest set bit
    3. If n is power of 2, n & (n - 1) == 0
    4. Edge case: n must be > 0

    COMPLEXITY:
    ──────────
    Time: O(1) — Single bitwise operation
    Space: O(1)
    """
    return n > 0 and (n & (n - 1)) == 0


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Missing Number
# ════════════════════════════════════════════════════════════════════════

def missing_number(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array containing n distinct numbers taken from [0, n],
    find the one missing number.

    Example:
        Input: [3, 0, 1]
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. XOR approach:
       - XOR all indices (0 to n) and all numbers
       - The result is the missing number
       - Because x ^ x = 0, duplicates cancel
    2. Mathematical: n*(n+1)/2 - sum(nums)
       - Fine in Python; in Java/Go with 32-bit ints, n*(n+1) overflows
         once n exceeds ~46,340. Use long, or XOR, which never overflows
    3. Cyclic placement (Arrays Q8) and sorting also work; XOR is the
       O(1)-space answer with no overflow concerns

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1)
    """
    missing = len(nums)  # n

    for i, num in enumerate(nums):
        missing ^= i ^ num

    return missing


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Sum of Two Integers (No +/- operators)
# ════════════════════════════════════════════════════════════════════════

def get_sum(a: int, b: int) -> int:
    """
    QUESTION:
    ─────────
    Given two integers, return their sum without using '+' or '-'.

    Example:
        Input: a = 1, b = 2
        Output: 3

    THOUGHT PROCESS:
    ────────────────
    1. a ^ b gives sum WITHOUT carries
    2. (a & b) << 1 gives the carry bits
    3. Repeat until carry = 0:
       - sum = a ^ b
       - carry = (a & b) << 1
       - a = sum, b = carry
    4. Handle Python's infinite bit representation:
       - Mask to 32 bits: a & 0xFFFFFFFF. Without the mask, a negative
         operand makes the carry shift left forever (infinite loop).
       - Convert back: if the 32-bit result has bit 31 set it is
         negative; ~(a ^ MASK) sign-extends it (same as a - 2**32)
    5. Overflow wraps like a Java int: get_sum(2**31 - 1, 1) == -2**31
    6. In Java/Go/C the loop needs no masking: the fixed width does it

    COMPLEXITY:
    ──────────
    Time: O(1) — At most 32 iterations
    Space: O(1)
    """
    MASK = 0xFFFFFFFF  # 32-bit mask
    MAX_INT = 0x7FFFFFFF

    while b != 0:
        a, b = (a ^ b) & MASK, ((a & b) << 1) & MASK

    # If result is > MAX_INT, it's negative in 32-bit
    return a if a <= MAX_INT else ~(a ^ MASK)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Find the Difference (XOR)
# ════════════════════════════════════════════════════════════════════════

def find_the_difference(s: str, t: str) -> str:
    """
    QUESTION:
    ─────────
    Given two strings s and t, where t is generated by shuffling s and
    adding one extra character, find that extra character.

    Example:
        Input: s = "abcd", t = "abcde"
        Output: "e"

    THOUGHT PROCESS:
    ────────────────
    1. XOR all characters from both strings
    2. Paired characters cancel out (x ^ x = 0)
    3. The remaining character is the answer
    4. This works for any character (not just letters)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through both strings
    Space: O(1)
    """
    result = 0
    for char in s + t:
        result ^= ord(char)
    return chr(result)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Maximum XOR of Two Numbers in an Array
# ════════════════════════════════════════════════════════════════════════

def find_maximum_xor(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an integer array, find the maximum XOR of any two numbers.

    Example:
        Input: [3, 10, 5, 25, 2, 8]
        Output: 28  (5 ^ 25 = 28)

    THOUGHT PROCESS:
    ────────────────
    1. Brute force: Check all O(n²) pairs
    2. Greedy + Trie approach: O(n × 32) = O(n)
       - Build a Trie from binary representations (MSB to LSB)
       - For each number, traverse Trie choosing opposite bit when
         possible to maximize XOR
    3. Alternative: Bit-by-bit greedy using hash set:
       - For each bit from MSB (31 down to 0):
         - See if we can achieve current_prefix | (1 << bit)
         - Use hash set of prefixes to check
    4. Why greedy is right: a 1 at a higher bit outweighs ALL lower bits
       combined (2^i > 2^i - 1), so always grab the higher bit if you can.

    COMPLEXITY:
    ──────────
    Time: O(n × 32) = O(n) — Each number processed for each bit
    Space: O(n × 32) = O(n) — Trie of all numbers
    """

    class BitTrieNode:
        def __init__(self):
            self.children = {}

    # Build Trie over bits 31..0 (inputs are 0 <= x < 2^31 on LeetCode;
    # negatives would need an offset or a sign-aware first level)
    root = BitTrieNode()
    for num in nums:
        node = root
        for i in range(31, -1, -1):
            bit = (num >> i) & 1
            if bit not in node.children:
                node.children[bit] = BitTrieNode()
            node = node.children[bit]

    # Find max XOR for each number
    max_xor = 0
    for num in nums:
        node = root
        current_xor = 0
        for i in range(31, -1, -1):
            bit = (num >> i) & 1
            # Greedy: choose opposite bit if available
            opposite = 1 - bit
            if opposite in node.children:
                current_xor |= (1 << i)  # Set this bit in result
                node = node.children[opposite]
            else:
                node = node.children[bit]  # Must take same bit

        max_xor = max(max_xor, current_xor)

    return max_xor


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("BIT MANIPULATION — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Single Number")
    print("-" * 40)
    nums = [4, 1, 2, 1, 2]
    print(f"   Input: {nums}")
    print(f"   Single: {single_number(nums)}")

    # Q2
    print("\n2️⃣  Single Number II")
    print("-" * 40)
    nums = [2, 2, 3, 2]
    print(f"   Input: {nums}")
    print(f"   Single: {single_number_ii(nums)}")

    # Q3
    print("\n3️⃣  Number of 1 Bits")
    print("-" * 40)
    n = 11  # 1011
    print(f"   n={n} (binary: {bin(n)})")
    print(f"   Hamming weight: {hamming_weight(n)}")

    # Q4
    print("\n4️⃣  Counting Bits")
    print("-" * 40)
    print(f"   n=5: {count_bits(5)}")

    # Q5
    print("\n5️⃣  Reverse Bits")
    print("-" * 40)
    n = 43261596
    print(f"   Original: {n} ({bin(n)})")
    print(f"   Reversed: {reverse_bits(n)} ({bin(reverse_bits(n))})")

    # Q6
    print("\n6️⃣  Power of Two")
    print("-" * 40)
    for n in [1, 16, 18, 0]:
        print(f"   {n}: {is_power_of_two(n)}")

    # Q7
    print("\n7️⃣  Missing Number")
    print("-" * 40)
    nums = [3, 0, 1]
    print(f"   Input: {nums}")
    print(f"   Missing: {missing_number(nums)}")

    # Q8
    print("\n8️⃣  Sum of Two Integers")
    print("-" * 40)
    print(f"   1 + 2 = {get_sum(1, 2)}")
    print(f"   (-1) + 1 = {get_sum(-1, 1)}")

    # Q9
    print("\n9️⃣  Find the Difference")
    print("-" * 40)
    s, t = "abcd", "abcde"
    print(f"   s={s}, t={t}")
    print(f"   Extra char: '{find_the_difference(s, t)}'")

    # Q10
    print("\n🔟  Maximum XOR of Two Numbers")
    print("-" * 40)
    nums = [3, 10, 5, 25, 2, 8]
    print(f"   Input: {nums}")
    print(f"   Max XOR: {find_maximum_xor(nums)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
