"""Tests for big_file_upload.py. Run: python3 -m unittest test_big_file_upload"""

import asyncio
import random
import tempfile
import unittest

from big_file_upload import (
    GIB, MIB, ChecksumMismatchError, ChunkConflictError, ChunkCorruptedError,
    ChunkInProgressError, ClientCrashed, FlakyNetwork, IncompleteUploadError,
    InMemoryChunkStorage, InvalidRequestError, InvalidStateError, LocalChunkStorage,
    RateLimitedError, RetryPolicy, UploadClient, UploadExpiredError, UploadPolicy,
    UploadService, UploadState, sha256_hex,
)

SMALL = UploadPolicy(min_chunk_size=4, default_chunk_size=4, max_file_size=1 * MIB,
                     bandwidth_bytes_per_sec=10 * MIB, bandwidth_burst_bytes=10 * MIB)
NO_DELAY = RetryPolicy(base_delay=0)


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def chunks_of(data, size):
    return [data[i:i + size] for i in range(0, len(data), size)]


class Base(unittest.IsolatedAsyncioTestCase):
    def make(self, policy=SMALL, storage=None):
        self.clock = FakeClock()
        self.storage = storage or InMemoryChunkStorage()
        self.svc = UploadService(self.storage, policy=policy, clock=self.clock)
        return self.svc

    async def start(self, data, user="u", **kw):
        return await self.svc.initiate(user, "f.bin", len(data), "application/octet-stream",
                                       sha256=sha256_hex(data), **kw)

    async def put(self, session, index, data):
        piece = data[index * session.chunk_size:(index + 1) * session.chunk_size]
        return await self.svc.upload_chunk(session.upload_id, index, piece, sha256_hex(piece))


class PolicyTest(unittest.TestCase):
    def test_chunk_size_respects_s3_part_limits(self):
        p = UploadPolicy()
        self.assertEqual(p.chunk_size_for(1 * GIB, preferred=1 * MIB), 5 * MIB)   # min part size
        size = p.chunk_size_for(100 * GIB, preferred=5 * MIB)
        self.assertGreater(size, 10 * MIB)
        self.assertLessEqual(-(-100 * GIB // size), 10_000)


class HappyPathTest(Base):
    async def test_out_of_order_parallel_upload_assembles_exact_bytes(self):
        self.make()
        data = bytes(range(256)) * 3 + b"tail"                    # 772 bytes -> 193 chunks of 4
        s = await self.start(data)
        order = list(range(s.total_chunks))
        random.Random(3).shuffle(order)
        await asyncio.gather(*(self.put(s, i, data) for i in order))
        done = await self.svc.complete(s.upload_id)
        self.assertEqual(done.status, UploadState.COMPLETED)
        self.assertEqual(await self.storage.read_object(done.final_key), data)
        self.assertEqual(done.final_sha256, sha256_hex(data))
        self.assertFalse([k for k in self.storage.objects if k.startswith("tmp/")])   # temp chunks gone

    async def test_zero_byte_file(self):
        self.make()
        s = await self.start(b"")
        self.assertEqual(s.total_chunks, 0)
        done = await self.svc.complete(s.upload_id)
        self.assertEqual(await self.storage.read_object(done.final_key), b"")

    async def test_complete_is_idempotent_and_scan_moves_to_ready(self):
        self.make()
        data = b"abcdefgh"
        s = await self.start(data)
        for i in range(2):
            await self.put(s, i, data)
        first = await self.svc.complete(s.upload_id)
        again = await self.svc.complete(s.upload_id)
        self.assertIs(first, again)
        await self.svc.record_scan_result(s.upload_id, clean=False)
        self.assertEqual(s.status, UploadState.QUARANTINED)
        await self.svc.record_scan_result(s.upload_id, clean=True)    # false positive released
        self.assertEqual(s.status, UploadState.READY)

    async def test_local_filesystem_backend(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(storage=LocalChunkStorage(root))
            data = b"0123456789abcdefXYZ"
            s = await self.start(data)
            await asyncio.gather(*(self.put(s, i, data) for i in range(s.total_chunks)))
            done = await self.svc.complete(s.upload_id)
            self.assertEqual(await self.storage.read_object(done.final_key), data)
            with self.assertRaises(InvalidRequestError):
                await self.storage.put_chunk("../escape", b"x")


class ResumeTest(Base):
    async def test_contiguous_offset_vs_received_bytes(self):
        self.make()
        data = b"aaaabbbbccccdd"
        s = await self.start(data)
        await self.put(s, 0, data)
        r = await self.put(s, 2, data)
        self.assertEqual(r.received_bytes, 8)
        self.assertEqual(r.contiguous_offset, 4)                  # chunk 1 missing: resume at byte 4
        self.assertEqual(await self.svc.missing_chunks(s.upload_id), [1, 3])
        await self.put(s, 1, data)
        self.assertEqual(await self.svc.get_offset(s.upload_id), 12)
        await self.put(s, 3, data)
        self.assertEqual(await self.svc.get_offset(s.upload_id), 14)

    async def test_client_crash_then_resume_sends_only_missing_chunks(self):
        self.make()
        data = random.Random(1).randbytes(400)                    # 100 chunks
        net = FlakyNetwork(self.svc, drop={5: 2, 50: 1}, crash_after=30)
        client = UploadClient(net, "u", concurrency=4, retry=NO_DELAY, rng=random.Random(0))
        with self.assertRaises(ClientCrashed):
            await client.upload(data, "f.bin")
        upload_id = client.last_upload_id
        missing = await self.svc.missing_chunks(upload_id)
        self.assertTrue(0 < len(missing) < 100)

        resumed = UploadClient(self.svc, "u", concurrency=8, retry=NO_DELAY)
        done = await resumed.upload(data, "f.bin", upload_id=upload_id)
        self.assertEqual(resumed.chunks_sent, len(missing))
        self.assertEqual(await self.storage.read_object(done.final_key), data)

    async def test_complete_with_gaps_lists_missing(self):
        self.make()
        data = b"aaaabbbbcccc"
        s = await self.start(data)
        await self.put(s, 1, data)
        with self.assertRaises(IncompleteUploadError) as ctx:
            await self.svc.complete(s.upload_id)
        self.assertEqual(ctx.exception.missing, [0, 2])


class IntegrityTest(Base):
    async def test_chunk_checksum_and_size_validation(self):
        self.make()
        s = await self.start(b"aaaabbbbcc")
        with self.assertRaises(ChecksumMismatchError):
            await self.svc.upload_chunk(s.upload_id, 0, b"aaaa", sha256_hex(b"zzzz"))
        with self.assertRaises(InvalidRequestError):              # last chunk is 2 bytes, not 4
            await self.svc.upload_chunk(s.upload_id, 2, b"cccc", sha256_hex(b"cccc"))
        with self.assertRaises(InvalidRequestError):
            await self.svc.upload_chunk(s.upload_id, 3, b"cc", sha256_hex(b"cc"))

    async def test_duplicate_is_idempotent_but_different_bytes_conflict(self):
        self.make()
        data = b"aaaabbbb"
        s = await self.start(data)
        self.assertFalse((await self.put(s, 0, data)).duplicate)
        self.assertTrue((await self.put(s, 0, data)).duplicate)
        with self.assertRaises(ChunkConflictError):
            await self.svc.upload_chunk(s.upload_id, 0, b"XXXX", sha256_hex(b"XXXX"))

    async def test_corruption_at_rest_is_detected_and_repaired(self):
        self.make()
        data = b"aaaabbbbcccc"
        s = await self.start(data)
        for i in range(3):
            await self.put(s, i, data)
        self.storage.objects[s.chunks[1].storage_key] = b"bXbb"   # bit rot in storage
        with self.assertRaises(ChunkCorruptedError) as ctx:
            await self.svc.complete(s.upload_id)
        self.assertEqual(ctx.exception.chunks, [1])
        self.assertEqual(s.status, UploadState.IN_PROGRESS)
        await self.put(s, 1, data)                                # client re-sends just that chunk
        done = await self.svc.complete(s.upload_id)
        self.assertEqual(await self.storage.read_object(done.final_key), data)

    async def test_whole_file_checksum_mismatch_fails(self):
        self.make()
        data = b"aaaabbbb"
        s = await self.svc.initiate("u", "f.bin", 8, "x", sha256=sha256_hex(b"something else"))
        for i in range(2):
            await self.put(s, i, data)
        with self.assertRaises(ChecksumMismatchError):
            await self.svc.complete(s.upload_id)
        self.assertEqual(s.status, UploadState.FAILED)
        self.assertEqual(self.svc.limiter.active_uploads("u"), 0)

    async def test_storage_failure_during_assembly_returns_to_in_progress(self):
        class BrokenCompose(InMemoryChunkStorage):
            fail = True

            async def compose(self, dest_key, part_keys):
                if self.fail:
                    self.fail = False
                    raise OSError("disk full")
                await super().compose(dest_key, part_keys)

        self.make(storage=BrokenCompose())
        data = b"aaaabbbb"
        s = await self.start(data)
        for i in range(2):
            await self.put(s, i, data)
        with self.assertRaises(OSError):
            await self.svc.complete(s.upload_id)
        self.assertEqual(s.status, UploadState.IN_PROGRESS)       # not stranded in ASSEMBLING
        done = await self.svc.complete(s.upload_id)
        self.assertEqual(done.status, UploadState.COMPLETED)


class ValidationTest(Base):
    async def test_rejects_bad_filenames_and_sizes(self):
        self.make()
        for name in ("../etc/passwd", "a/b", "a\\b", "", ".hidden", "x\x00y"):
            with self.assertRaises(InvalidRequestError, msg=name):
                await self.svc.initiate("u", name, 10, "x")
        with self.assertRaises(InvalidRequestError):
            await self.svc.initiate("u", "big.bin", 2 * MIB, "x")
        with self.assertRaises(InvalidRequestError):
            await self.svc.initiate("u", "neg.bin", -1, "x")


class ConcurrencyTest(Base):
    async def test_same_chunk_concurrently_is_written_once(self):
        class SlowStorage(InMemoryChunkStorage):
            writes = 0

            async def put_chunk(self, key, data):
                SlowStorage.writes += 1
                await asyncio.sleep(0.02)
                await super().put_chunk(key, data)

        self.make(storage=SlowStorage())
        data = b"aaaabbbb"
        s = await self.start(data)
        results = await asyncio.gather(self.put(s, 0, data), self.put(s, 0, data),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ChunkInProgressError) for r in results), 1)
        self.assertEqual(SlowStorage.writes, 1)

    async def test_complete_and_cancel_refused_while_chunk_in_flight(self):
        gate = asyncio.Event()

        class GatedStorage(InMemoryChunkStorage):
            async def put_chunk(self, key, data):
                await gate.wait()
                await super().put_chunk(key, data)

        self.make(storage=GatedStorage())
        data = b"aaaabbbb"
        s = await self.start(data)
        gate.set()
        await self.put(s, 0, data)
        gate.clear()
        pending = asyncio.ensure_future(self.put(s, 1, data))
        await asyncio.sleep(0.01)                                 # chunk 1 is now in flight
        with self.assertRaises(ChunkInProgressError):
            await self.svc.complete(s.upload_id)
        with self.assertRaises(ChunkInProgressError):
            await self.svc.cancel(s.upload_id)
        gate.set()
        await pending
        self.assertEqual((await self.svc.complete(s.upload_id)).status, UploadState.COMPLETED)

    async def test_parallel_chunks_of_one_upload_overlap(self):
        """The per-upload lock is not held during storage writes."""
        class SlowStorage(InMemoryChunkStorage):
            async def put_chunk(self, key, data):
                await asyncio.sleep(0.05)
                await super().put_chunk(key, data)

        self.make(storage=SlowStorage())
        data = b"x" * 40                                          # 10 chunks
        s = await self.start(data)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.gather(*(self.put(s, i, data) for i in range(10)))
        self.assertLess(loop.time() - t0, 0.3)                    # not 10 x 0.05 serialised


class LimitsTest(Base):
    async def test_concurrent_upload_limit_and_no_leak_on_rejection(self):
        policy = UploadPolicy(min_chunk_size=4, default_chunk_size=4, max_concurrent_uploads=2,
                              daily_quota_bytes=100, bandwidth_burst_bytes=MIB)
        self.make(policy)
        a = await self.svc.initiate("u", "a", 10, "x")
        await self.svc.initiate("u", "b", 10, "x")
        with self.assertRaises(RateLimitedError):
            await self.svc.initiate("u", "c", 10, "x")
        self.assertTrue(await self.svc.cancel(a.upload_id))
        await self.svc.initiate("u", "c", 10, "x")                # slot freed by cancel
        # Quota rejection must not consume a concurrency slot.
        self.assertEqual(self.svc.limiter.active_uploads("u"), 2)

    async def test_daily_quota_is_refunded_on_cancel(self):
        policy = UploadPolicy(min_chunk_size=4, default_chunk_size=4, daily_quota_bytes=100,
                              bandwidth_burst_bytes=MIB)
        self.make(policy)
        s = await self.svc.initiate("u", "a", 80, "x")
        with self.assertRaises(RateLimitedError):
            await self.svc.initiate("u", "b", 30, "x")
        self.assertEqual(self.svc.limiter.active_uploads("u"), 1)
        await self.svc.cancel(s.upload_id)
        await self.svc.initiate("u", "b", 30, "x")

    async def test_bandwidth_token_bucket(self):
        policy = UploadPolicy(min_chunk_size=4, default_chunk_size=4, max_file_size=MIB,
                              bandwidth_bytes_per_sec=8, bandwidth_burst_bytes=8)
        self.make(policy)
        data = b"aaaabbbbcccc"
        s = await self.start(data)
        await self.put(s, 0, data)
        await self.put(s, 1, data)                                # burst of 8 used up
        with self.assertRaises(RateLimitedError) as ctx:
            await self.put(s, 2, data)
        self.assertAlmostEqual(ctx.exception.retry_after, 0.5)    # 4 bytes at 8 B/s
        self.clock.t += 0.5
        await self.put(s, 2, data)


class ExpiryTest(Base):
    async def test_expired_upload_rejected_then_garbage_collected(self):
        self.make()
        data = b"aaaabbbb"
        s = await self.start(data)
        await self.put(s, 0, data)
        self.clock.t += SMALL.session_ttl - 1
        self.clock.t += 2                                         # past expiry
        with self.assertRaises(UploadExpiredError):
            await self.put(s, 1, data)
        self.assertEqual(await self.svc.collect_garbage(), [s.upload_id])
        self.assertEqual(s.status, UploadState.EXPIRED)
        self.assertFalse(self.storage.objects)                    # chunks deleted
        self.assertEqual(self.svc.limiter.active_uploads("u"), 0)

    async def test_activity_slides_the_expiry(self):
        self.make()
        data = b"aaaabbbbcccc"
        s = await self.start(data)
        self.clock.t += SMALL.session_ttl - 10
        await self.put(s, 0, data)                                # activity on day ~7
        self.clock.t += SMALL.session_ttl - 10
        await self.put(s, 1, data)                                # still alive
        self.assertEqual(await self.svc.collect_garbage(), [])

    async def test_cancel_terminal_upload_is_noop(self):
        self.make()
        s = await self.start(b"")
        await self.svc.complete(s.upload_id)
        self.assertFalse(await self.svc.cancel(s.upload_id))
        with self.assertRaises(InvalidStateError):
            await self.svc.upload_chunk(s.upload_id, 0, b"", sha256_hex(b""))


if __name__ == "__main__":
    unittest.main()
