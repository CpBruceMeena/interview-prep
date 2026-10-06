"""Tests for search_platform.py. Run: python3 -m unittest test_search_platform"""

import math
import threading
import unittest
from datetime import datetime

from search_platform import (
    Analyzer, BM25Scorer, Document, PopularityBoost, QueryParser, RecencyBoost,
    SearchEngine, SortOrder, TfIdfScorer, levenshtein, light_stem, sample_documents,
)


def ids(hits):
    return [h.doc.doc_id for h in hits]


def doc(doc_id, title="", body="", **kw):
    return Document(doc_id, title, body, **kw)


class AnalyzerTest(unittest.TestCase):
    def test_index_and_query_forms_meet(self):
        a = Analyzer()
        self.assertEqual(a.terms("Databases, INDEXING & designed!"), ["database", "index", "design"])
        self.assertEqual(a.terms("design-patterns"), ["design", "pattern"])

    def test_stop_words_dropped_but_positions_kept(self):
        tokens = Analyzer().analyze("design of the system")
        self.assertEqual([(t.term, t.position) for t in tokens], [("design", 0), ("system", 3)])

    def test_stemmer_guards(self):
        self.assertEqual(light_stem("class"), "class")      # not "clas"
        self.assertEqual(light_stem("libraries"), "library")
        self.assertEqual(light_stem("bus"), "bus")          # too short to touch
        self.assertEqual(light_stem("2024"), "2024")
        self.assertEqual(light_stem("string"), "string")    # not "str"
        self.assertEqual(light_stem("running"), "run")
        self.assertEqual(light_stem("installed"), "install")


class QueryParserTest(unittest.TestCase):
    def test_operators_and_phrases(self):
        q = QueryParser(Analyzer()).parse('python +design -java "system of design" -"bad idea"')
        self.assertEqual(q.should, ["python"])
        self.assertEqual(q.must, ["design"])
        self.assertEqual(q.must_not, ["java", "bad", "idea"])
        self.assertEqual(q.phrases, [["system", "", "design"]])   # stop word leaves a gap

    def test_stop_word_only_query_is_empty(self):
        self.assertTrue(QueryParser(Analyzer()).parse("the of and").is_empty)


class ScorerTest(unittest.TestCase):
    def test_bm25_idf_is_rarer_is_better_and_never_negative(self):
        s = BM25Scorer()
        rare = s.score(tf=1, df=1, n_docs=100, doc_len=10, avg_len=10)
        common = s.score(tf=1, df=100, n_docs=100, doc_len=10, avg_len=10)
        self.assertGreater(rare, common)
        self.assertGreater(common, 0)

    def test_bm25_tf_saturates_and_length_normalises(self):
        s = BM25Scorer(k1=1.2, b=0.75)
        tf1, tf10, tf100 = (s.score(tf, 5, 100, 10, 10) for tf in (1, 10, 100))
        self.assertLess(tf100 - tf10, tf10 - tf1)                 # diminishing returns
        idf = math.log(1 + (100 - 5 + 0.5) / 5.5)
        self.assertLess(tf100, idf * 2.2)                         # bounded by idf * (k1 + 1)
        short = s.score(2, 5, 100, doc_len=5, avg_len=10)
        long = s.score(2, 5, 100, doc_len=40, avg_len=10)
        self.assertGreater(short, long)

    def test_bm25_matches_hand_computation(self):
        idf = math.log(1 + (10 - 2 + 0.5) / (2 + 0.5))
        expected = idf * 3 * 2.2 / (3 + 1.2 * (1 - 0.75 + 0.75 * 20 / 10))
        self.assertAlmostEqual(BM25Scorer().score(3, 2, 10, 20, 10), expected)

    def test_tfidf(self):
        expected = (1 + math.log(4)) * (math.log(11 / 3) + 1)
        self.assertAlmostEqual(TfIdfScorer().score(4, 2, 10, 0, 0), expected)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.index_many(sample_documents())

    def test_or_query_ranks_doc_matching_more_terms_first(self):
        self.assertEqual(ids(self.engine.search("python design"))[0], "1")

    def test_must_and_must_not(self):
        self.assertEqual(set(ids(self.engine.search("+microservices patterns"))), {"3", "6"})
        self.assertNotIn("6", ids(self.engine.search("design -microservices")))
        self.assertEqual(ids(self.engine.search("+microservices +python")), [])

    def test_must_only_query_returns_results(self):
        # The old version returned nothing for a query with only +terms.
        self.assertEqual(set(ids(self.engine.search("+python"))), {"1", "4"})

    def test_phrase_requires_adjacency(self):
        self.assertEqual(ids(self.engine.search('"system design"')), ["2"])
        self.assertEqual(ids(self.engine.search('"design system"')), [])

    def test_phrase_does_not_span_two_tags(self):
        e = SearchEngine()
        e.index(doc("t", tags=("python", "design")))
        self.assertEqual(ids(e.search('"python design"')), [])
        self.assertEqual(ids(e.search("python design")), ["t"])

    def test_stemming_matches_inflections(self):
        self.assertEqual(ids(self.engine.search("databases")), ["5"])
        self.assertIn("6", ids(self.engine.search("design")))   # title says "Designing"

    def test_fuzzy_fallback_for_typos_only(self):
        # "desing" has no postings; it expands to "design" (2 edits) at a discount.
        self.assertEqual(set(ids(self.engine.search("desing"))), {"1", "2", "5", "6"})
        fuzzy = SearchEngine(fuzzy=False)
        fuzzy.index_many(sample_documents())
        self.assertEqual(fuzzy.search("desing"), [])

    def test_title_outweighs_body(self):
        e = SearchEngine()
        e.index(doc("body", "notes", "a short note about kafka"))
        e.index(doc("title", "kafka", "a short note about queues"))
        self.assertEqual(ids(e.search("kafka")), ["title", "body"])

    def test_category_filter_and_sorts(self):
        hits = self.engine.search("microservices", category="Architecture", sort=SortOrder.NEWEST)
        self.assertEqual(ids(hits), ["6", "3"])
        hits = self.engine.search("python", sort=SortOrder.POPULARITY)
        self.assertEqual(ids(hits), ["4", "1"])

    def test_limit(self):
        self.assertEqual(len(self.engine.search("design", limit=2)), 2)

    def test_search_has_no_side_effects(self):
        before = [h.score for h in self.engine.search("python")]
        for _ in range(5):
            self.engine.search("python")
        self.assertEqual([h.score for h in self.engine.search("python")], before)


class BoostTest(unittest.TestCase):
    def test_recency_and_popularity(self):
        now = datetime(2026, 1, 31)
        rec = RecencyBoost(now, half_life_days=30, weight=0.5)
        self.assertAlmostEqual(rec.factor(doc("a", created_at=now)), 1.5)
        self.assertAlmostEqual(rec.factor(doc("a", created_at=datetime(2026, 1, 1))), 1.25)
        pop = PopularityBoost(weight=0.1)
        self.assertAlmostEqual(pop.factor(doc("a", popularity=999)), 1.3)

    def test_recency_breaks_a_tie(self):
        now = datetime(2026, 1, 31)
        e = SearchEngine(boosts=[RecencyBoost(now)])
        e.index(doc("old", "kafka guide", created_at=datetime(2020, 1, 1)))
        e.index(doc("new", "kafka guide", created_at=datetime(2026, 1, 30)))
        self.assertEqual(ids(e.search("kafka")), ["new", "old"])


class IndexMaintenanceTest(unittest.TestCase):
    def test_reindex_replaces_old_terms_and_stats(self):
        e = SearchEngine()
        e.index(doc("1", "kafka", "streams"))
        e.index(doc("1", "redis", "cache"))
        self.assertEqual(e.search("kafka"), [])
        self.assertEqual(ids(e.search("redis")), ["1"])
        self.assertEqual(e.stats()["documents"], 1)
        self.assertEqual(e.stats()["terms"], 2)

    def test_delete_removes_postings_and_suggestions(self):
        e = SearchEngine()
        e.index(doc("1", "kubernetes operators"))
        e.index(doc("2", "kubernetes basics"))
        self.assertTrue(e.delete("1"))
        self.assertFalse(e.delete("1"))
        self.assertEqual(e.search("operators"), [])
        self.assertEqual(e.suggest("op"), [])
        self.assertEqual(e.suggest("ku"), ["kubernetes"])

    def test_suggest_ranks_by_document_frequency(self):
        e = SearchEngine()
        e.index(doc("1", "redis"))
        e.index(doc("2", "redis replication"))
        e.index(doc("3", "redshift"))
        self.assertEqual(e.suggest("red"), ["redis", "redshift"])
        self.assertEqual(e.suggest("re", limit=1), ["redis"])
        self.assertEqual(e.suggest("zzz"), [])


class LevenshteinTest(unittest.TestCase):
    def test_distances(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("desing", "design"), 2)      # a transposition costs 2
        self.assertEqual(levenshtein("abcdef", "uvwxyz", max_dist=2), 3)  # early exit


class ConcurrencyTest(unittest.TestCase):
    def test_concurrent_indexing_and_searching(self):
        e = SearchEngine()
        errors = []

        def writer(start):
            for i in range(start, start + 200):
                e.index(doc(str(i), f"topic{i % 7} shared", "common body text"))

        def reader():
            try:
                for _ in range(200):
                    for hit in e.search("shared common", limit=5):
                        assert hit.score > 0
                    e.suggest("top")
            except Exception as exc:     # surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i * 200,)) for i in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(e.stats()["documents"], 800)
        self.assertEqual(len(e.search("+shared", limit=1000)), 800)
        self.assertEqual(len(e.search("topic3", limit=1000)), len([i for i in range(800) if i % 7 == 3]))


if __name__ == "__main__":
    unittest.main()
