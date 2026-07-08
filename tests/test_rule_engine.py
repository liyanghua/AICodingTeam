"""Test rule engine evaluation."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import from shells/report_generator/engine
ENGINE_MODULE = PROJECT_ROOT / "shells" / "report_generator" / "engine"
sys.path.insert(0, str(ENGINE_MODULE))

import rule_engine


class TestRuleEngine(unittest.TestCase):
    """Test rule evaluation logic."""
    
    def test_strong_hot_gene_match(self):
        """Strong hot gene matches when growth >= 30 and CR5 <= 40."""
        result = rule_engine.evaluate_strong_hot_gene({
            "category_gmv_growth": 35,
            "cr5": 38,
        })
        self.assertEqual(result["rule_id"], "strong_hot_gene")
        self.assertTrue(result["matched"])
        self.assertEqual(result["output_label"], "强热基因确认")
    
    def test_strong_hot_gene_no_match_growth(self):
        """Strong hot gene fails when growth < 30."""
        result = rule_engine.evaluate_strong_hot_gene({
            "category_gmv_growth": 25,
            "cr5": 35,
        })
        self.assertFalse(result["matched"])
        self.assertEqual(result["output_label"], "非强热基因")
    
    def test_strong_hot_gene_no_match_cr5(self):
        """Strong hot gene fails when CR5 > 40."""
        result = rule_engine.evaluate_strong_hot_gene({
            "category_gmv_growth": 35,
            "cr5": 45,
        })
        self.assertFalse(result["matched"])
    
    def test_trend_hot_gene_match(self):
        """Trend hot gene matches when search >= 50 and note >= 20."""
        result = rule_engine.evaluate_trend_hot_gene({
            "search_index_mom": 60,
            "note_growth": 25,
        })
        self.assertTrue(result["matched"])
        self.assertEqual(result["output_label"], "趋势热基因确认")
    
    def test_trend_hot_gene_boundary(self):
        """Trend hot gene boundary at 50/20."""
        result = rule_engine.evaluate_trend_hot_gene({
            "search_index_mom": 50,
            "note_growth": 20,
        })
        self.assertTrue(result["matched"])
    
    def test_differentiated_opportunity_match(self):
        """Differentiated opportunity matches."""
        result = rule_engine.evaluate_differentiated_opportunity_gene({
            "top20_homogenization": 65,
            "longtail_gmv_ratio": 30,
        })
        self.assertTrue(result["matched"])
        self.assertEqual(result["output_label"], "差异化机会确认")
    
    def test_opportunity_score_priority(self):
        """Opportunity score >= 85 is priority."""
        result = rule_engine.evaluate_opportunity_score({
            "market_size": 20,
            "growth_rate": 20,
            "competition_intensity": 15,
            "brand_fit": 15,
            "supply_chain_feasibility": 10,
            "differentiation_strength": 10,
        })
        self.assertEqual(result["score"], 90)
        self.assertEqual(result["output_label"], "优先立项开发")
        self.assertTrue(result["matched"])
    
    def test_opportunity_score_test_tier(self):
        """Opportunity score 70-84 is test tier."""
        result = rule_engine.evaluate_opportunity_score({
            "market_size": 18,
            "growth_rate": 18,
            "competition_intensity": 12,
            "brand_fit": 12,
            "supply_chain_feasibility": 10,
            "differentiation_strength": 5,
        })
        self.assertEqual(result["score"], 75)
        self.assertEqual(result["output_label"], "小批量测试")
        self.assertTrue(result["matched"])
    
    def test_opportunity_score_observe_tier(self):
        """Opportunity score 60-69 is observe tier."""
        result = rule_engine.evaluate_opportunity_score({
            "market_size": 15,
            "growth_rate": 15,
            "competition_intensity": 10,
            "brand_fit": 10,
            "supply_chain_feasibility": 10,
            "differentiation_strength": 5,
        })
        self.assertEqual(result["score"], 65)
        self.assertEqual(result["output_label"], "继续观察")
        self.assertTrue(result["matched"])
    
    def test_opportunity_score_no_develop(self):
        """Opportunity score < 60 is no develop."""
        result = rule_engine.evaluate_opportunity_score({
            "market_size": 10,
            "growth_rate": 10,
            "competition_intensity": 10,
            "brand_fit": 10,
            "supply_chain_feasibility": 10,
            "differentiation_strength": 5,
        })
        self.assertEqual(result["score"], 55)
        self.assertEqual(result["output_label"], "暂不开发")
        self.assertFalse(result["matched"])
    
    def test_eval_rule_dispatch(self):
        """eval_rule dispatches to correct evaluator."""
        result = rule_engine.eval_rule("strong_hot_gene", {
            "category_gmv_growth": 35,
            "cr5": 35,
        })
        self.assertEqual(result["rule_id"], "strong_hot_gene")
        self.assertTrue(result["matched"])
    
    def test_eval_rule_unknown(self):
        """eval_rule returns error for unknown rule."""
        result = rule_engine.eval_rule("nonexistent_rule", {})
        self.assertEqual(result["rule_id"], "nonexistent_rule")
        self.assertFalse(result["matched"])
        self.assertEqual(result["output_label"], "未配置规则")
        self.assertIn("unknown_rule", result["evidence"]["warning"])


class TestRuleEngineCLI(unittest.TestCase):
    """Test CLI interface."""
    
    def test_cli_stdin_stdout(self):
        """CLI reads from stdin, writes to stdout."""
        engine_path = ENGINE_MODULE / "rule_engine.py"
        request = {
            "rule_id": "opportunity_score",
            "inputs": {
                "market_size": 20,
                "growth_rate": 20,
                "competition_intensity": 15,
                "brand_fit": 15,
                "supply_chain_feasibility": 15,
                "differentiation_strength": 15,
            },
        }
        
        proc = subprocess.run(
            [sys.executable, str(engine_path)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
        )
        
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["rule_id"], "opportunity_score")
        self.assertEqual(result["score"], 100)


if __name__ == "__main__":
    unittest.main()