from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from shells.report_generator.engine import rule_engine, rules


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = (
    PROJECT_ROOT
    / "document-to-skill-engineering-package"
    / "skills"
    / "market_insight"
    / "output_schemas"
    / "hot_product_gene_table.json"
)


class EvidenceAwareGeneRuleTests(unittest.TestCase):
    def test_absent_signals_are_unavailable_and_do_not_count_as_false(self) -> None:
        hit = rules.eval_rule(
            "strong_hot_gene",
            {"sample_size": 50, "top50_ratio": 0.35},
        )

        self.assertFalse(hit.matched)
        self.assertEqual("insufficient_evidence", hit.evidence["classification_status"])
        self.assertEqual(1, hit.evidence["available_count"])
        self.assertEqual(1, hit.evidence["matched_count"])
        self.assertEqual("matched", hit.evidence["signals"]["top50_ratio"]["status"])
        self.assertEqual("unavailable", hit.evidence["signals"]["top100_ratio"]["status"])
        self.assertEqual("unavailable", hit.evidence["signals"]["top100_ratio"]["source_status"])
        self.assertIsNone(hit.evidence["signals"]["top100_ratio"]["matched"])

    def test_top50_signal_requires_a_sample_of_at_least_50(self) -> None:
        too_small = rules.eval_rule(
            "strong_hot_gene",
            {"sample_size": 49, "top50_ratio": 0.80, "top100_ratio": 0.25},
        )
        sufficient = rules.eval_rule(
            "strong_hot_gene",
            {"sample_size": 50, "top50_ratio": 0.80, "top100_ratio": 0.25},
        )

        self.assertFalse(too_small.matched)
        self.assertEqual(
            "insufficient_sample",
            too_small.evidence["signals"]["top50_ratio"]["source_status"],
        )
        self.assertEqual(1, too_small.evidence["available_count"])
        self.assertTrue(sufficient.matched)

    def test_ratio_signals_reject_interval_and_index_substitutes(self) -> None:
        hit = rules.eval_rule(
            "strong_hot_gene",
            {
                "sample_size": 50,
                "top50_ratio": 0.31,
                "pay_buyer_count_interval": [100, 200],
                "gmv_or_transaction_index": 99999,
                "transaction_index": 99999,
            },
        )

        self.assertFalse(hit.matched)
        self.assertEqual("unavailable", hit.evidence["signals"]["buyer_ratio"]["source_status"])
        self.assertEqual("unavailable", hit.evidence["signals"]["gmv_ratio"]["source_status"])
        self.assertNotIn("pay_buyer_count_interval", hit.evidence["evidence_fields"])
        self.assertNotIn("transaction_index", hit.evidence["evidence_fields"])
        self.assertNotIn("gmv_or_transaction_index", hit.evidence["evidence_fields"])

    def test_gene_rules_remain_independent_multi_label_classifiers(self) -> None:
        inputs = {
            "sample_size": 100,
            "top50_ratio": 0.35,
            "top100_ratio": 0.25,
            "buyer_ratio": 0.32,
            "gmv_ratio": 0.33,
            "high_growth_product_ratio": 0.35,
            "keyword_growth": 0.25,
            "buyer_growth_30d": 0.55,
            "cross_platform_hot": True,
            "review_painpoint_ratio": 0.12,
            "qa_concern_ratio": 0.11,
            "top50_supply_count": 4,
            "price_band_supply_ratio": 0.10,
            "price_band_buyer_ratio": 0.28,
        }

        hits = [
            rules.eval_rule(rule_id, inputs)
            for rule_id in (
                "strong_hot_gene",
                "trend_hot_gene",
                "differentiated_opportunity_gene",
            )
        ]

        self.assertEqual([True, True, True], [hit.matched for hit in hits])
        self.assertEqual(3, len({hit.rule_id for hit in hits}))

    def test_rule_engine_facade_delegates_to_core_rules(self) -> None:
        delegated = rules.RuleHit(
            rule_id="strong_hot_gene",
            matched=True,
            output_label="强爆款基因",
            evidence={"classification_status": "matched"},
        )
        with mock.patch.object(rules, "eval_rule", return_value=delegated) as evaluator:
            result = rule_engine.eval_rule("strong_hot_gene", {"top50_ratio": 0.3})

        evaluator.assert_called_once_with("strong_hot_gene", {"top50_ratio": 0.3})
        self.assertEqual("strong_hot_gene", result["rule_id"])
        self.assertTrue(result["matched"])


class HotProductGeneSchemaTests(unittest.TestCase):
    def test_schema_declares_analysis_contract_and_dimension_evidence(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual("hot-product-gene-analysis-v1", schema["$id"])
        self.assertEqual(
            {
                "product_profiles",
                "dimension_findings",
                "gene_groups",
                "coverage",
                "risks",
                "human_confirmation",
                "source_trace",
            },
            set(schema["required"]),
        )
        dimension = schema["$defs"]["dimension"]
        self.assertEqual(
            {"raw_value", "normalized_tags", "source_status", "confidence", "evidence_fields"},
            set(dimension["required"]),
        )
        self.assertFalse(dimension["additionalProperties"])
        self.assertTrue(
            {"api_fact", "missing", "deterministic_relative_band", "pi_derived_unconfirmed"}
            <= set(dimension["properties"]["source_status"]["enum"])
        )
        self.assertEqual("string", dimension["properties"]["evidence_fields"]["items"]["type"])
        self.assertTrue(
            {"metrics", "classifications", "member_row_ids"}
            <= set(schema["$defs"]["gene_group"]["properties"])
        )
        self.assertEqual("string", schema["properties"]["risks"]["items"]["type"])
        self.assertEqual(
            "#/$defs/coverage_item",
            schema["$defs"]["coverage"]["additionalProperties"]["$ref"],
        )
        schema_versions = schema["properties"]["schema_version"].get("enum", [])
        statuses = schema["properties"]["status"]["enum"]
        self.assertIn("hot-product-gene-analysis-confirmed-v1", schema_versions)
        self.assertIn("confirmed", statuses)


if __name__ == "__main__":
    unittest.main()
