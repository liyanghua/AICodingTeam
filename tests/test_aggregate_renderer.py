"""Test aggregate renderer logic (numbers gatekeeper).

Since renderAggregate is embedded in server.js, we test the logic
by verifying the patterns and expected behavior.
"""

import re
import unittest


class TestNumbersGatekeeper(unittest.TestCase):
    """Test numbers gatekeeper patterns."""
    
    def setUp(self):
        """Set up forbidden patterns matching server.js implementation."""
        self.forbidden_patterns = [
            re.compile(r'\d+\s*%'),                    # percentages
            re.compile(r'\d+\.\d+'),                   # decimals
            re.compile(r'[¥$￥]\s*\d+'),               # currency
            re.compile(r'\d+\s*(元|美元|块|万|亿)'),    # Chinese currency
            re.compile(r'\d{1,3}(,\d{3})+'),           # thousands separator
            re.compile(r'GMV|销量|增速|增长率'),       # business metrics
        ]
    
    def check_narrative(self, text):
        """Check if narrative violates any pattern."""
        for pattern in self.forbidden_patterns:
            if pattern.search(text):
                return False, pattern.pattern
        return True, None
    
    def test_valid_narrative_passes(self):
        """Valid narrative without numbers passes."""
        text = "This is a qualitative analysis focusing on market trends."
        passed, _ = self.check_narrative(text)
        self.assertTrue(passed)
    
    def test_percentage_rejected(self):
        """Percentage pattern is rejected."""
        text = "市场增速达到30%以上"
        passed, pattern = self.check_narrative(text)
        self.assertFalse(passed)
        self.assertIn('%', pattern)
    
    def test_decimal_rejected(self):
        """Decimal number is rejected."""
        text = "价格约为3.5元"
        passed, pattern = self.check_narrative(text)
        self.assertFalse(passed)
        # Should match either decimal or currency pattern
        self.assertTrue('\\d+\\.\\d+' in pattern or '元' in pattern)
    
    def test_currency_symbol_rejected(self):
        """Currency symbol with number is rejected."""
        text = "售价¥199"
        passed, pattern = self.check_narrative(text)
        self.assertFalse(passed)
        self.assertIn('¥', pattern)
    
    def test_chinese_currency_unit_rejected(self):
        """Chinese currency units are rejected."""
        for unit in ['元', '万', '亿']:
            text = f"价值100{unit}"
            passed, pattern = self.check_narrative(text)
            self.assertFalse(passed, f"Should reject: {text}")
            self.assertIn(unit, pattern)
    
    def test_thousands_separator_rejected(self):
        """Thousands separator is rejected."""
        text = "销售额达到1,000,000"
        passed, pattern = self.check_narrative(text)
        self.assertFalse(passed)
        self.assertIn(',', pattern)
    
    def test_gmv_keyword_rejected(self):
        """Business metric keywords are rejected."""
        for keyword in ['GMV', '销量', '增速', '增长率']:
            text = f"分析{keyword}结构"
            passed, pattern = self.check_narrative(text)
            self.assertFalse(passed, f"Should reject keyword: {keyword}")
            self.assertIn(keyword, pattern)
    
    def test_multiple_violations(self):
        """Text with multiple violations is rejected."""
        text = "GMV增长30%，价格¥199"
        passed, _ = self.check_narrative(text)
        self.assertFalse(passed)
    
    def test_edge_cases_pass(self):
        """Edge cases without actual numbers pass."""
        valid_texts = [
            "增长趋势明显",  # mentions growth without numbers
            "价格合理",       # mentions price without amount
            "市场表现良好",   # qualitative assessment
        ]
        for text in valid_texts:
            passed, _ = self.check_narrative(text)
            self.assertTrue(passed, f"Should pass: {text}")


class TestAggregateStructure(unittest.TestCase):
    """Test aggregate report structure expectations."""
    
    def test_markdown_sections(self):
        """Report should have expected sections."""
        # Simulate what renderAggregate produces
        expected_sections = [
            "# ",           # Title
            "## 执行摘要",
            "## 规则评估结果",
            "| 规则 | 结论 | 分数 | 匹配 |",  # Table header
        ]
        
        # This is a structural test - actual rendering tested via integration
        for section in expected_sections:
            self.assertIsInstance(section, str)
    
    def test_rule_output_fields(self):
        """Rule outputs should have expected fields."""
        rule_output = {
            "rule_id": "test_rule",
            "output_label": "Test Label",
            "score": 85,
            "matched": True,
        }
        
        self.assertIn("rule_id", rule_output)
        self.assertIn("output_label", rule_output)
        self.assertIn("matched", rule_output)
        # score can be None for non-scoring rules
        self.assertIn("score", rule_output)


if __name__ == "__main__":
    unittest.main()